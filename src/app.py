import os
import sys
import json
import threading
import time
from datetime import datetime
from pathlib import Path
import asyncio
import nest_asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import math

from flask import Flask, render_template, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from src.utils.twitter_scraper import TwitterScraper
from src.utils.database import save_twitter_stats, get_latest_leaderboard, get_historical_data, import_existing_json_data

# Enable nested event loops
nest_asyncio.apply()

# Load environment variables
load_dotenv(project_root / 'config' / '.env')

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# Add custom Jinja2 filters
def format_number(value):
    """Format large numbers with K, M, B suffixes"""
    if value is None:
        return "0"
    
    value = float(value)
    if value >= 1_000_000_000:
        return f"{value/1_000_000_000:.1f}B"
    elif value >= 1_000_000:
        return f"{value/1_000_000:.1f}M"
    elif value >= 1_000:
        return f"{value/1_000:.1f}K"
    else:
        return f"{value:,.0f}"

app.jinja_env.filters['format_number'] = format_number

# Setup paths
DATA_DIR = project_root / 'src' / 'data'
LOG_DIR = project_root / 'src' / 'logs'

# Create directories if they don't exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Global variables to store leaderboard data
current_leaderboard = []  # Initialize as empty list
last_update = None
alerts = []
update_lock = threading.Lock()
scraper = None  # Global scraper instance
event_loop = None  # Global event loop

def initialize_scraper():
    """Initialize the scraper in a new event loop"""
    global scraper, event_loop
    try:
        # Create new event loop if needed
        if not event_loop or event_loop.is_closed():
            event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(event_loop)
        
        # Initialize scraper
        scraper = event_loop.run_until_complete(TwitterScraper.create())
        
        if not scraper:
            raise Exception("Scraper initialization returned None")
            
        logger.info("Successfully initialized Twitter scraper")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing scraper: {str(e)}")
        if event_loop and not event_loop.is_closed():
            try:
                # Clean up any pending tasks
                pending = asyncio.all_tasks(event_loop)
                event_loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as cleanup_error:
                logger.error(f"Error cleaning up tasks: {str(cleanup_error)}")
            finally:
                event_loop.close()
                event_loop = None
        return False

async def update_leaderboard():
    """Update leaderboard data periodically"""
    global current_leaderboard, last_update, alerts
    
    try:
        while True:
            logger.info("Starting leaderboard update...")
            
            try:
                # Get list of tokens/usernames to track
                tokens = await scraper.get_tracked_tokens()
                
                # Get Twitter data
                twitter_data = await scraper.get_twitter_data(tokens)
                
                # Get market data
                market_data = await scraper.get_market_data(tokens)
                
                # Process the data
                if twitter_data and market_data:
                    with update_lock:
                        current_leaderboard = process_leaderboard_data(twitter_data, market_data)
                        last_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Save data to database instead of JSON file
                        for entry in current_leaderboard:
                            save_twitter_stats(entry)
                
                # Sleep for 5 minutes (300 seconds)
                await asyncio.sleep(300)
                
            except Exception as e:
                logger.error(f"Error updating leaderboard: {str(e)}")
                await asyncio.sleep(60)  # Wait a minute before retrying
                
    except asyncio.CancelledError:
        logger.info("Update task cancelled")

def process_leaderboard_data(twitter_data, market_data):
    """Process and combine Twitter and market data for the leaderboard"""
    leaderboard = []
    
    for username, data in twitter_data.items():
        # Get market info for this token
        market_info = market_data.get(username, {})
        
        # Calculate growth metrics
        growth_metrics = data.get('growth_metrics', {})
        
        entry = {
            'username': username,
            'bio': data.get('bio', ''),
            'verified': data.get('verified', False),
            'followers_count': data.get('followers_count', 0),
            'following_count': data.get('following_count', 0),
            'tweets_count': data.get('tweets_count', 0),
            'location': data.get('location', ''),
            'market_cap': market_info.get('market_cap', 0),
            'price': market_info.get('price', 0),
            'price_change_24h': market_info.get('price_change_24h', 0),
            'growth_5m': growth_metrics.get('change_5m', 0),
            'growth_15m': growth_metrics.get('change_15m', 0),
            'growth_30m': growth_metrics.get('change_30m', 0),
            'growth_1h': growth_metrics.get('change_1h', 0),
            'growth_4h': growth_metrics.get('change_4h', 0),
            'growth_6h': growth_metrics.get('change_6h', 0),
            'growth_12h': growth_metrics.get('change_12h', 0),
            'growth_18h': growth_metrics.get('change_18h', 0),
            'growth_24h': growth_metrics.get('change_24h', 0),
            'growth_status': determine_growth_status(growth_metrics),
            'engagement_rate': data.get('engagement_rate', 0),
            'engagement_details': data.get('engagement_details', {}),
            'created_at': datetime.now().strftime('%Y-%m-%d'),
            'twitter_score': calculate_twitter_score(
                data.get('followers_count', 0),
                data.get('engagement_rate', 0),
                growth_metrics.get('change_1h', 0),
                growth_metrics.get('change_24h', 0),
                data.get('verified', False)
            )
        }
        leaderboard.append(entry)
    
    # Sort by Twitter score (descending)
    leaderboard.sort(key=lambda x: x['twitter_score'], reverse=True)
    return leaderboard

def determine_growth_status(growth_metrics):
    """Determine the growth status based on various metrics"""
    growth_5m = growth_metrics.get('change_5m', 0)
    growth_15m = growth_metrics.get('change_15m', 0)
    growth_30m = growth_metrics.get('change_30m', 0)
    growth_1h = growth_metrics.get('change_1h', 0)
    
    # Check for spike (rapid growth in short term)
    if growth_5m >= 2 or growth_15m >= 5 or growth_30m >= 8 or growth_1h >= 10:
        return '🚀 Spiking'
    
    # Check for fast growth
    if growth_1h >= 5:
        return '📈 Fast Growth'
    
    # Check for steady growth
    if growth_1h > 0:
        return '↗️ Growing'
    
    # Check for decline
    if growth_1h < 0:
        return '↘️ Declining'
    
    return '➡️ Stable'

def calculate_engagement_rate(followers, likes, retweets):
    """Calculate engagement rate based on followers, likes, and retweets"""
    if followers == 0:
        return 0
    return (likes + retweets) / followers

def calculate_twitter_score(followers, engagement_rate, growth_1h, growth_24h, verified):
    """Calculate Twitter score based on various metrics"""
    # Base score from followers (logarithmic scale)
    base_score = math.log10(max(followers, 1)) * 10
    
    # Engagement multiplier (0.5 to 1.5)
    engagement_multiplier = 1 + (engagement_rate * 100)
    engagement_multiplier = max(0.5, min(1.5, engagement_multiplier))
    
    # Growth multiplier (1.0 to 2.0)
    growth_multiplier = 1 + (max(growth_1h, 0) / 100) + (max(growth_24h, 0) / 200)
    growth_multiplier = max(1.0, min(2.0, growth_multiplier))
    
    # Verification bonus
    verified_bonus = 1.2 if verified else 1.0
    
    # Calculate final score
    score = base_score * engagement_multiplier * growth_multiplier * verified_bonus
    return round(score, 1)

def run_async_update():
    """Run the async update task in the background"""
    global event_loop
    try:
        # Use existing event loop or create new one
        if not event_loop:
            event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(event_loop)
        
        # Create and run update task
        update_task = event_loop.create_task(update_leaderboard())
        event_loop.run_forever()
    except Exception as e:
        logger.error(f"Error in async update: {str(e)}")
    finally:
        if event_loop and not event_loop.is_closed():
            event_loop.close()

@app.route('/')
def index():
    """Render the main leaderboard page"""
    try:
        # Get leaderboard data from database
        leaderboard_data = get_latest_leaderboard()
        
        # If no data in database, use current_leaderboard
        if not leaderboard_data and current_leaderboard:
            leaderboard_data = current_leaderboard
        
        # Sort by Twitter score (descending)
        leaderboard_data.sort(key=lambda x: x.get('twitter_score', 0), reverse=True)
        
        # Get timestamp
        timestamp = last_update or datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Render template with data
        return render_template(
            'index.html',
            leaderboard=leaderboard_data,
            last_update=timestamp,
            alerts=alerts
        )
    except Exception as e:
        logger.error(f"Error rendering index: {str(e)}")
        return render_template(
            'index.html',
            leaderboard=[],
            last_update=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            alerts=[f"Error loading data: {str(e)}"]
        )

@app.route('/api/leaderboard')
def get_leaderboard():
    """API endpoint to get leaderboard data"""
    try:
        # Get leaderboard data from database
        leaderboard_data = get_latest_leaderboard()
        
        # If no data in database, use current_leaderboard
        if not leaderboard_data and current_leaderboard:
            leaderboard_data = current_leaderboard
            
        return jsonify({
            'timestamp': last_update or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': leaderboard_data
        })
    except Exception as e:
        logger.error(f"Error in API: {str(e)}")
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data': []
        }), 500

@app.route('/api/history/<username>')
def get_user_history(username):
    """API endpoint to get historical data for a specific user"""
    try:
        # Get historical data from database
        history_data = get_historical_data(username)
        
        return jsonify({
            'username': username,
            'history': history_data
        })
    except Exception as e:
        logger.error(f"Error getting history for {username}: {str(e)}")
        return jsonify({
            'error': str(e),
            'username': username,
            'history': []
        }), 500

def start_background_tasks():
    """Start background tasks"""
    # Import existing JSON data into the database
    import_existing_json_data()
    
    # Initialize scraper
    if initialize_scraper():
        # Start update thread
        update_thread = threading.Thread(target=run_async_update)
        update_thread.daemon = True
        update_thread.start()
    else:
        logger.error("Failed to initialize scraper, background tasks not started")

if __name__ == '__main__':
    # Start background tasks
    start_background_tasks()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=5000)