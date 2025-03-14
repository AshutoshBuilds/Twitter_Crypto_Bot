import sqlite3
import os
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database file path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'twitter_metrics.db')

def ensure_db_directory():
    """Ensure the directory for the database exists"""
    db_dir = os.path.dirname(DB_PATH)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)

def init_db():
    """Initialize the database with required tables"""
    ensure_db_directory()
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        bio TEXT,
        location TEXT,
        verified BOOLEAN,
        created_at TEXT
    )
    ''')
    
    # Create metrics table for time-series data
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        timestamp TEXT,
        followers_count INTEGER,
        following_count INTEGER,
        tweets_count INTEGER,
        engagement_rate REAL,
        twitter_score INTEGER,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')
    
    # Create engagement_details table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS engagement_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_id INTEGER,
        total_engagement REAL,
        tweets_analyzed INTEGER,
        FOREIGN KEY (metric_id) REFERENCES metrics (id)
    )
    ''')
    
    conn.commit()
    conn.close()
    
    logger.info("Database initialized successfully")

def get_user_id(username):
    """Get user ID from username, create if not exists"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    
    if result:
        user_id = result[0]
    else:
        cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
        user_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    return user_id

def save_twitter_stats(stats):
    """Save Twitter stats to the database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Validate input
        if not isinstance(stats, dict):
            raise ValueError(f"Expected dictionary, got {type(stats)}")
            
        # Check for required username field
        if 'username' not in stats or not stats['username']:
            raise ValueError("Missing required field: username")
            
        username = stats['username']
        
        # Get or create user
        cursor.execute(
            "SELECT id FROM users WHERE username = ?", 
            (username,)
        )
        result = cursor.fetchone()
        
        if result:
            user_id = result[0]
            # Update user info
            cursor.execute(
                "UPDATE users SET bio = ?, location = ?, verified = ?, created_at = ? WHERE id = ?",
                (
                    stats.get('bio', ''),
                    stats.get('location', ''),
                    stats.get('verified', False),
                    stats.get('created_at', datetime.now().strftime('%Y-%m-%d')),
                    user_id
                )
            )
        else:
            # Create new user
            cursor.execute(
                "INSERT INTO users (username, bio, location, verified, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    username,
                    stats.get('bio', ''),
                    stats.get('location', ''),
                    stats.get('verified', False),
                    stats.get('created_at', datetime.now().strftime('%Y-%m-%d'))
                )
            )
            user_id = cursor.lastrowid
        
        # Insert metrics
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute(
            """
            INSERT INTO metrics 
            (user_id, timestamp, followers_count, following_count, tweets_count, 
             engagement_rate, twitter_score)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                timestamp,
                int(stats.get('followers_count', 0)),
                int(stats.get('following_count', 0)),
                int(stats.get('tweets_count', 0)),
                float(stats.get('engagement_rate', 0.0)),
                int(stats.get('twitter_score', 0))
            )
        )
        metric_id = cursor.lastrowid
        
        # Insert engagement details if available
        if 'engagement_details' in stats and isinstance(stats['engagement_details'], dict):
            engagement_details = stats['engagement_details']
            cursor.execute(
                "INSERT INTO engagement_details (metric_id, total_engagement, tweets_analyzed) VALUES (?, ?, ?)",
                (
                    metric_id,
                    float(engagement_details.get('total_engagement', 0.0)),
                    int(engagement_details.get('tweets_analyzed', 0))
                )
            )
        
        conn.commit()
        logger.info(f"Successfully saved stats for {username} to database")
        return True
    
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving stats to database for {stats.get('username', 'unknown')}: {str(e)}")
        return False
    
    finally:
        conn.close()

def get_latest_leaderboard():
    """Get the latest leaderboard data from the database"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        cursor = conn.cursor()
        
        # Get the latest metrics for each user
        query = """
        WITH RankedMetrics AS (
            SELECT 
                m.*,
                u.username,
                u.bio,
                u.location,
                u.verified,
                ROW_NUMBER() OVER (PARTITION BY m.user_id ORDER BY m.timestamp DESC) as rn
            FROM metrics m
            JOIN users u ON m.user_id = u.id
        )
        SELECT * FROM RankedMetrics WHERE rn = 1
        ORDER BY followers_count DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        # Convert to list of dictionaries
        leaderboard = []
        for row in results:
            try:
                # Get previous metrics to calculate change
                cursor.execute("""
                    SELECT followers_count 
                    FROM metrics 
                    WHERE user_id = ? AND timestamp < ? 
                    ORDER BY timestamp DESC 
                    LIMIT 1
                """, (row['user_id'], row['timestamp']))
                
                prev_result = cursor.fetchone()
                prev_followers = prev_result['followers_count'] if prev_result else row['followers_count']
                follower_change = row['followers_count'] - prev_followers
                
                # Get engagement details
                cursor.execute("""
                    SELECT total_engagement, tweets_analyzed 
                    FROM engagement_details 
                    WHERE metric_id = ?
                """, (row['id'],))
                
                engagement_row = cursor.fetchone()
                engagement_details = {
                    'total_engagement': engagement_row['total_engagement'] if engagement_row else 0,
                    'tweets_analyzed': engagement_row['tweets_analyzed'] if engagement_row else 0
                }
                
                # Create entry with all required fields
                entry = {
                    'username': row['username'],
                    'followers_count': row['followers_count'],
                    'following_count': row['following_count'],
                    'tweets_count': row['tweets_count'],
                    'follower_change': follower_change,
                    'bio': row['bio'] or '',
                    'location': row['location'] or '',
                    'verified': bool(row['verified']),
                    'engagement_rate': row['engagement_rate'],
                    'engagement_details': engagement_details,
                    'twitter_score': row['twitter_score'],
                    # Add default values for fields that might be expected by the template
                    'price': 0.0,
                    'price_change_24h': 0.0,
                    'market_cap': 0,
                    'growth_5m': 0.0,
                    'growth_15m': 0.0,
                    'growth_30m': 0.0,
                    'growth_1h': 0.0,
                    'growth_4h': 0.0,
                    'growth_6h': 0.0,
                    'growth_12h': 0.0,
                    'growth_18h': 0.0,
                    'growth_24h': 0.0,
                    'growth_status': '➡️ Stable'
                }
                
                leaderboard.append(entry)
            except Exception as e:
                logger.error(f"Error processing row for {row['username']}: {str(e)}")
                continue
        
        return leaderboard
    except Exception as e:
        logger.error(f"Error getting leaderboard data: {str(e)}")
        return []
    finally:
        if conn:
            conn.close()

def get_historical_data(username, days=30):
    """Get historical follower data for a specific user"""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.id FROM users u WHERE u.username = ?
        """, (username,))
        
        user_row = cursor.fetchone()
        if not user_row:
            logger.warning(f"No user found with username: {username}")
            return []
        
        user_id = user_row['id']
        
        # Get metrics for the specified time period
        cursor.execute("""
            SELECT timestamp, followers_count
            FROM metrics
            WHERE user_id = ?
            ORDER BY timestamp ASC
        """, (user_id,))
        
        results = cursor.fetchall()
        
        # Limit to the most recent 'days' entries if there are more
        if len(results) > days:
            results = results[-days:]
            
        history = []
        for row in results:
            try:
                history.append({
                    'timestamp': row['timestamp'],
                    'followers_count': row['followers_count']
                })
            except Exception as e:
                logger.error(f"Error processing historical data row: {str(e)}")
                continue
        
        return history
    except Exception as e:
        logger.error(f"Error getting historical data for {username}: {str(e)}")
        return []
    finally:
        if conn:
            conn.close()

def import_existing_json_data():
    """Import existing JSON data into the database"""
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    
    # Look for leaderboard.json and any historical files
    json_files = [f for f in os.listdir(data_dir) if f.endswith('.json')]
    
    for json_file in json_files:
        file_path = os.path.join(data_dir, json_file)
        try:
            # Try different encodings to handle potential encoding issues
            encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
            data = None
            
            for encoding in encodings:
                try:
                    with open(file_path, 'r', encoding=encoding) as f:
                        data = json.load(f)
                    break  # If successful, break the loop
                except UnicodeDecodeError:
                    continue  # Try the next encoding
                except json.JSONDecodeError:
                    continue  # Try the next encoding
            
            if data is None:
                logger.error(f"Failed to decode {json_file} with any encoding")
                continue
                
            # Handle different JSON formats
            stats_list = []
            if isinstance(data, list):
                # Direct list of stats
                stats_list = data
            elif isinstance(data, dict) and 'data' in data and isinstance(data['data'], list):
                # Wrapped in a data field
                stats_list = data['data']
            
            # Process each stat entry
            for stats in stats_list:
                # Validate required fields
                if not isinstance(stats, dict):
                    continue
                    
                if 'username' not in stats or not stats['username']:
                    continue
                
                # Ensure all required fields have default values if missing
                stats_copy = {
                    'username': stats.get('username', ''),
                    'bio': stats.get('bio', ''),
                    'location': stats.get('location', ''),
                    'verified': stats.get('verified', False),
                    'followers_count': stats.get('followers_count', 0),
                    'following_count': stats.get('following_count', 0),
                    'tweets_count': stats.get('tweets_count', 0),
                    'engagement_rate': stats.get('engagement_rate', 0.0),
                    'twitter_score': stats.get('twitter_score', 0),
                    'created_at': stats.get('created_at', datetime.now().strftime('%Y-%m-%d'))
                }
                
                # Add engagement details if available
                if 'engagement_details' in stats and isinstance(stats['engagement_details'], dict):
                    stats_copy['engagement_details'] = stats['engagement_details']
                else:
                    stats_copy['engagement_details'] = {
                        'total_engagement': 0.0,
                        'tweets_analyzed': 0
                    }
                
                # Save to database
                save_twitter_stats(stats_copy)
            
            logger.info(f"Imported data from {json_file}")
        except Exception as e:
            logger.error(f"Error importing data from {json_file}: {str(e)}")

# Initialize the database when the module is imported
init_db() 