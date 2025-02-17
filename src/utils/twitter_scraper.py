from datetime import datetime, timedelta
import time
import logging
import re
import os
import random
from dotenv import load_dotenv
import json
import math
import asyncio
from playwright.async_api import async_playwright
from tqdm import tqdm
import aiohttp
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TwitterScraper:
    def __init__(self):
        """Initialize the Twitter scraper"""
        # Load environment variables
        load_dotenv()
        self.username = os.getenv('TWITTER_USERNAME')
        self.password = os.getenv('TWITTER_PASSWORD')
        
        if not self.username or not self.password:
            raise ValueError("Twitter credentials not found in .env file")
        
        self.browser = None
        self.context = None
        self.page = None
        self.playwright = None
        
        # Initialize follower history storage
        self.follower_history = {}
        self.last_update_time = None
        
        # Spike detection thresholds
        self.SPIKE_THRESHOLD_PERCENT = 5  # 5% increase in an hour is considered a spike
        self.RAPID_GROWTH_THRESHOLD = 1000  # 1000 followers per hour is rapid growth
        
    def save_follower_data(self, username, followers_count):
        """Save follower data with timestamp"""
        try:
            data_dir = Path('data')
            data_dir.mkdir(exist_ok=True)
            
            file_path = data_dir / f'{username}_history.json'
            current_time = int(time.time())
            
            # Load existing data
            history = []
            if file_path.exists():
                with open(file_path, 'r') as f:
                    history = json.load(f)
            
            # Add new data point
            history.append({
                'timestamp': current_time,
                'followers': followers_count
            })
            
            # Keep only last 24 hours of data
            cutoff_time = current_time - (24 * 60 * 60)
            history = [point for point in history if point['timestamp'] > cutoff_time]
            
            # Sort by timestamp
            history.sort(key=lambda x: x['timestamp'])
            
            # Save updated history
            with open(file_path, 'w') as f:
                json.dump(history, f)
            
            return True
        except Exception as e:
            logger.error(f"Error saving follower data: {str(e)}")
            return False

    def _calculate_growth_metrics(self, username, history):
        """Calculate growth metrics for various time intervals"""
        if not history:
            return {
                'change_5m': 0,
                'change_15m': 0,
                'change_30m': 0,
                'change_1h': 0,
                'change_4h': 0,
                'change_6h': 0,
                'change_12h': 0,
                'change_18h': 0,
                'change_24h': 0
            }
        
        current_time = int(time.time())
        current_followers = history[-1]['followers']
        
        # Define time intervals in seconds
        intervals = {
            'change_5m': 5 * 60,
            'change_15m': 15 * 60,
            'change_30m': 30 * 60,
            'change_1h': 60 * 60,
            'change_4h': 4 * 60 * 60,
            'change_6h': 6 * 60 * 60,
            'change_12h': 12 * 60 * 60,
            'change_18h': 18 * 60 * 60,
            'change_24h': 24 * 60 * 60
        }
        
        metrics = {}
        
        # Calculate changes for each interval
        for interval_name, seconds in intervals.items():
            interval_time = current_time - seconds
            # Find the closest data point before the interval
            interval_point = None
            for point in reversed(history):
                if point['timestamp'] <= interval_time:
                    interval_point = point
                    break
            
            if interval_point:
                interval_followers = interval_point['followers']
                change = current_followers - interval_followers
                if interval_followers > 0:
                    metrics[interval_name] = (change / interval_followers) * 100
                else:
                    metrics[interval_name] = 0
            else:
                metrics[interval_name] = 0
        
        return metrics

    def _calculate_follower_growth(self, username):
        """Calculate follower growth over various time intervals"""
        try:
            file_path = Path('data') / f'{username}_history.json'
            if not file_path.exists():
                return {
                    'change_5m': 0, 'change_15m': 0, 'change_30m': 0,
                    'change_1h': 0, 'change_4h': 0, 'change_6h': 0,
                    'change_12h': 0, 'change_18h': 0, 'change_24h': 0,
                    'growth_rate': 0
                }

            with open(file_path, 'r') as f:
                history = json.load(f)

            if not history:
                return {
                    'change_5m': 0, 'change_15m': 0, 'change_30m': 0,
                    'change_1h': 0, 'change_4h': 0, 'change_6h': 0,
                    'change_12h': 0, 'change_18h': 0, 'change_24h': 0,
                    'growth_rate': 0
                }

            # Sort data points by timestamp
            data_points = sorted(history, key=lambda x: x['timestamp'])
            current_time = int(time.time())
            current_followers = data_points[-1]['followers']

            growth_metrics = self._calculate_growth_metrics(username, data_points)

            # Calculate hourly growth rate based on the last hour
            if growth_metrics['change_1h'] != 0:
                growth_rate = growth_metrics['change_1h']
            else:
                growth_rate = 0

            growth_metrics['growth_rate'] = growth_rate
            return growth_metrics

        except Exception as e:
            logger.error(f"Error calculating follower growth: {str(e)}")
            return {
                'change_5m': 0, 'change_15m': 0, 'change_30m': 0,
                'change_1h': 0, 'change_4h': 0, 'change_6h': 0,
                'change_12h': 0, 'change_18h': 0, 'change_24h': 0,
                'growth_rate': 0
            }

    def detect_follower_spike(self, username, current_followers):
        """Detect if there's a significant spike in followers"""
        try:
            file_path = Path('data') / f'{username}_history.json'
            if not file_path.exists():
                return False, 0
            
            with open(file_path, 'r') as f:
                history = json.load(f)
            
            if not history:
                return False, 0
            
            # Sort data points by timestamp
            data_points = sorted(history, key=lambda x: x['timestamp'])
            
            # Get the oldest data point within the last hour
            current_time = int(time.time())
            hour_ago = current_time - 3600
            
            old_point = None
            for point in data_points:
                if point['timestamp'] <= hour_ago:
                    old_point = point
                else:
                    break
            
            if not old_point:
                return False, 0
            
            # Calculate percentage change
            old_followers = old_point['followers']
            if old_followers == 0:
                return False, 0
            
            percent_change = ((current_followers - old_followers) / old_followers) * 100
            
            # Return True if change exceeds spike threshold
            return percent_change >= self.SPIKE_THRESHOLD_PERCENT, percent_change
            
        except Exception as e:
            logger.error(f"Error detecting follower spike: {str(e)}")
            return False, 0

    @classmethod
    async def create(cls):
        """Create and initialize a new TwitterScraper instance"""
        self = cls()
        
        try:
            # Initialize playwright
            self.playwright = await async_playwright().start()
            if not self.playwright:
                raise Exception("Failed to start playwright")

            logger.info("Playwright started successfully")

            # Launch browser with explicit wait
            self.browser = await self.playwright.chromium.launch(
                headless=True,  # Run in headless mode for stability
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            if not self.browser:
                raise Exception("Failed to launch browser")

            logger.info("Browser launched successfully")

            # Create context with explicit wait
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            if not self.context:
                raise Exception("Failed to create browser context")

            logger.info("Browser context created successfully")

            try:
                # Create new page
                self.page = await self.context.new_page()
                if not self.page:
                    raise Exception("Failed to create new page")

                logger.info("New page created successfully")

                # Set timeouts before any navigation
                self.page.set_default_timeout(60000)
                self.page.set_default_navigation_timeout(60000)

                # Test page functionality with a simple navigation
                try:
                    await self.page.goto('https://www.google.com', wait_until='domcontentloaded')
                    await self.page.wait_for_load_state('domcontentloaded')
                    logger.info("Page initialization successful")
                except Exception as nav_error:
                    raise Exception(f"Failed to verify page functionality: {str(nav_error)}")

                # Login to Twitter
                await self._login()
                logger.info("Twitter login successful")
                
                return self
                
            except Exception as page_error:
                logger.error(f"Error during page initialization: {str(page_error)}")
                await self._cleanup_resources()
                raise Exception(f"Page initialization failed: {str(page_error)}")
                
        except Exception as e:
            error_msg = f"Failed to create TwitterScraper instance: {str(e)}"
            logger.error(error_msg)
            await self._cleanup_resources()
            raise Exception(error_msg)

    async def _cleanup_resources(self):
        """Clean up browser resources"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}")

    async def _login(self):
        """Login to Twitter using Playwright"""
        try:
            # Navigate to login page
            await self.page.goto('https://twitter.com/i/flow/login', timeout=60000)
            await self.page.wait_for_load_state('networkidle', timeout=60000)
            await asyncio.sleep(2)
            
            # Enter username
            username_input = await self.page.wait_for_selector('input[autocomplete="username"]', timeout=30000)
            if not username_input:
                raise Exception("Username input field not found")
            
            await username_input.fill(self.username)
            await username_input.press('Enter')
            await asyncio.sleep(2)
            
            # Handle additional security if username is phone/email
            try:
                security_input = await self.page.wait_for_selector('input[data-testid="ocfEnterTextTextInput"]', timeout=5000)
                if security_input:
                    await security_input.fill(self.username)
                    await security_input.press('Enter')
                    await asyncio.sleep(2)
            except:
                pass  # No security check needed
            
            # Enter password
            password_input = await self.page.wait_for_selector('input[name="password"]', timeout=30000)
            if not password_input:
                raise Exception("Password input field not found")
            
            await password_input.fill(self.password)
            await password_input.press('Enter')
            await asyncio.sleep(3)
            
            # Verify login success
            try:
                # Check for successful login indicators
                success = await self.page.wait_for_selector('[data-testid="primaryColumn"]', timeout=30000)
                if not success:
                    raise Exception("Login verification failed")
                
                # Check for error messages
                error_selectors = [
                    'text="The username and password you entered did not match our records"',
                    'text="Something went wrong"',
                    'text="Verify your identity"'
                ]
                
                for selector in error_selectors:
                    error = await self.page.query_selector(selector)
                    if error:
                        raise Exception(f"Login failed: {await error.text_content()}")
                
                logger.info("Successfully logged in to Twitter")
                
            except Exception as e:
                # Take screenshot for debugging
                try:
                    await self.page.screenshot(path='login_error.png')
                    logger.info("Login error screenshot saved as login_error.png")
                except:
                    pass
                raise Exception(f"Login verification failed: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error logging in to Twitter: {str(e)}")
            raise

    def _parse_number(self, text):
        """Parse number from text (e.g., '1.5K' to 1500)"""
        if not text:
            return 0
        text = str(text).strip().upper()
        text = re.sub(r'[^\d.KM]', '', text)
        multiplier = 1
        
        if 'K' in text:
            multiplier = 1000
            text = text.replace('K', '')
        elif 'M' in text:
            multiplier = 1000000
            text = text.replace('M', '')
            
        try:
            return int(float(text) * multiplier)
        except:
            return 0

    def _calculate_twitter_score(self, followers, engagement_rate, verified):
        """
        Calculate Twitter Score similar to TwitterScore.io
        Score is based on followers, engagement rate, and verification status
        """
        # Base score from followers (logarithmic scale)
        if followers <= 0:
            return 0
        
        follower_score = (1000 * (1 + math.log10(followers))) / 7
        
        # Engagement multiplier (0.5 to 2.0)
        engagement_multiplier = 1 + (engagement_rate * 100)  # Convert to percentage
        engagement_multiplier = max(0.5, min(2.0, engagement_multiplier))
        
        # Verification bonus
        verification_bonus = 1.2 if verified else 1.0
        
        # Calculate final score
        score = follower_score * engagement_multiplier * verification_bonus
        
        # Normalize to 0-1000 scale
        normalized_score = min(1000, max(0, int(score)))
        
        return normalized_score

    async def scrape_account_stats(self, username):
        """Scrape account statistics using Playwright"""
        try:
            # Navigate to profile page with retry logic
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    # Use a more reliable navigation strategy
                    await self.page.goto(
                        f'https://twitter.com/{username}',
                        wait_until='domcontentloaded',  # Changed from networkidle to domcontentloaded
                        timeout=30000  # Reduced timeout to 30 seconds
                    )
                    
                    # Wait for specific elements instead of networkidle
                    try:
                        await self.page.wait_for_selector('[data-testid="UserName"]', timeout=20000)
                        break
                    except Exception as wait_error:
                        logger.warning(f"Waiting for profile elements: {str(wait_error)}")
                        retry_count += 1
                        if retry_count == max_retries:
                            raise
                        continue
                        
                except Exception as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        raise
                    logger.warning(f"Retry {retry_count}/{max_retries} for {username}: {str(e)}")
                    await asyncio.sleep(5)  # Wait before retry
            
            # Get follower and following counts with shorter timeouts
            stats = {
                'followers': '0',
                'following': '0',
                'tweets': '0'
            }
                    
            # Add retry logic for stats collection with shorter timeouts
            retry_count = 0
            while retry_count < max_retries:
                try:
                    # Wait for stats to load
                    await self.page.wait_for_selector('[data-testid="primaryColumn"]', timeout=10000)
                    await asyncio.sleep(2)  # Give time for dynamic content to load
                    
                    # Try multiple selector patterns
                    stats = {'followers': '0', 'following': '0', 'tweets': '0'}
                    patterns = [
                        # New Twitter structure
                        'a[href*="/following"] span span',
                        'a[href*="/followers"] span span',
                        'a[href*="/verified_followers"] span span',
                        # Backup patterns
                        '[data-testid="primaryColumn"] div[dir="ltr"] span',
                        'div[data-testid="UserProfileHeader_Items"] span'
                    ]
                    
                    for pattern in patterns:
                        elements = await self.page.query_selector_all(pattern)
                        for elem in elements:
                            if not elem:
                                continue
                                
                            text = await elem.text_content()
                            if not text or not any(c.isdigit() for c in text):
                                continue
                                
                            parent = await elem.evaluate('node => node.parentElement.parentElement.innerHTML')
                            if not parent:
                                continue
                                
                            parent = parent.lower()
                            if 'following' in parent and stats['following'] == '0':
                                stats['following'] = text.split(' ')[0]
                            elif 'followers' in parent and stats['followers'] == '0':
                                stats['followers'] = text.split(' ')[0]
                            elif ('posts' in parent or 'tweets' in parent) and stats['tweets'] == '0':
                                stats['tweets'] = text.split(' ')[0]
                    
                    # Verify we got at least some stats
                    if stats['followers'] == '0' and stats['following'] == '0' and stats['tweets'] == '0':
                        raise Exception("Failed to parse any stats")
                        
                    # Take a screenshot for debugging if needed
                    if retry_count > 0:
                        await self.page.screenshot(path=f'debug_stats_{username}.png')
                        
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count == max_retries:
                        raise
                    logger.warning(f"Retry {retry_count}/{max_retries} for stats collection: {str(e)}")
                    await asyncio.sleep(3)
            
            # Get location with shorter timeout
            try:
                location_elem = await self.page.wait_for_selector('[data-testid="UserLocation"]', timeout=5000)
                location = await location_elem.text_content() if location_elem else ""
            except:
                location = ""
                    
            # Get verification status
            try:
                verified = await self.page.is_visible('[data-testid="UserName"] [aria-label*="Verified"]', timeout=5000)
            except:
                verified = False
                    
            # Get bio with shorter timeout
            try:
                bio_elem = await self.page.wait_for_selector('[data-testid="UserDescription"]', timeout=5000)
                bio = await bio_elem.text_content() if bio_elem else ""
            except:
                bio = ""
            
            # Calculate engagement rate from recent tweets with shorter timeouts
            tweets = await self.page.query_selector_all('[data-testid="tweet"]')
            total_engagement = 0
            total_tweets = min(len(tweets), 5)  # Look at up to 5 recent tweets
            
            for tweet in tweets[:total_tweets]:
                try:
                    # Get likes
                    like_elem = await tweet.query_selector('[data-testid="like"]')
                    likes = self._parse_number(await like_elem.text_content()) if like_elem else 0
                    
                    # Get retweets
                    retweet_elem = await tweet.query_selector('[data-testid="retweet"]')
                    retweets = self._parse_number(await retweet_elem.text_content()) if retweet_elem else 0
                    
                    # Get replies
                    reply_elem = await tweet.query_selector('[data-testid="reply"]')
                    replies = self._parse_number(await reply_elem.text_content()) if reply_elem else 0
                    
                    # Calculate weighted engagement
                    weighted_engagement = likes + (retweets * 2) + (replies * 1.5)
                    total_engagement += weighted_engagement
                except Exception as e:
                    logger.error(f"Error parsing tweet engagement: {str(e)}")
                    continue
            
            # Calculate engagement rate
            followers_count = self._parse_number(stats['followers'])
            engagement_rate = total_engagement / (total_tweets * followers_count) if total_tweets > 0 and followers_count > 0 else 0
                    
            result = {
                'username': username,
                'followers_count': followers_count,
                'following_count': self._parse_number(stats['following']),
                'tweets_count': self._parse_number(stats['tweets']),
                'location': location,
                'bio': bio,
                'created_at': datetime.now().strftime('%Y-%m-%d'),
                'verified': verified,
                'engagement_rate': engagement_rate,
                'engagement_details': {
                    'total_engagement': total_engagement,
                    'tweets_analyzed': total_tweets
                },
                'twitter_score': self._calculate_twitter_score(
                    followers=followers_count,
                    engagement_rate=engagement_rate,
                    verified=verified
                )
            }
            
            logger.info(f"Successfully scraped stats for {username}: {result}")
            return result
                    
        except Exception as e:
            logger.error(f"Error scraping account stats for {username}: {str(e)}")
            return None

    async def generate_leaderboard(self, tokens, time_interval='3d'):
        """Generate leaderboard data using Playwright with parallel scraping"""
        try:
            results = []
            alerts = []
            
            # Create a new browser context for parallel scraping
            context = await self.browser.new_context()
            
            async def scrape_token(token):
                try:
                    # Create a new page for each token
                    page = await context.new_page()
                    
                    # Configure page
                    await page.set_viewport_size({"width": 1920, "height": 1080})
                    
                    # Get Twitter stats
                    stats = await self._scrape_account_stats_parallel(page, token)
                    if not stats:
                        await page.close()
                        return None
                        
                    # Save follower data for tracking
                    followers_count = stats['followers_count']
                    self.save_follower_data(token, followers_count)
                    
                    # Check for follower spikes
                    is_spike, spike_percent = self.detect_follower_spike(token, followers_count)
                    if is_spike:
                        alert_msg = f"🚨 ALERT: {token} has seen a {spike_percent:.1f}% increase in followers in the last hour!"
                        alerts.append(alert_msg)
                        logger.info(alert_msg)
                    
                    # Get follower growth metrics
                    growth_metrics = self._calculate_follower_growth(token)
                    
                    # Calculate percentage changes
                    pct_change_1h = (growth_metrics['change_1h'] / followers_count * 100) if followers_count > 0 else 0
                    pct_change_24h = (growth_metrics['change_24h'] / followers_count * 100) if followers_count > 0 else 0
                    
                    # Get market data
                    market_data = await self.get_market_data(token)
                    
                    # Determine growth status
                    if is_spike:
                        growth_status = "🚀 Spiking"
                    elif pct_change_24h > 1:
                        growth_status = "Growing Fast"
                    elif pct_change_24h > 0:
                        growth_status = "Growing"
                    elif pct_change_24h < -1:
                        growth_status = "Declining"
                    else:
                        growth_status = "Stable"
                    
                    # Combine all data
                    token_data = {
                        'token': token,
                        'twitter_stats': stats,
                        'market_data': market_data,
                        'follower_metrics': {
                            'total_followers': followers_count,
                            'change_1h': growth_metrics['change_1h'],
                            'change_24h': growth_metrics['change_24h'],
                            'pct_change_1h': pct_change_1h,
                            'pct_change_24h': pct_change_24h,
                            'growth_rate': growth_metrics['growth_rate'],
                            'growth_status': growth_status,
                            'hourly_rate': growth_metrics['growth_rate'],
                            'is_spiking': is_spike
                        }
                    }
                    
                    await page.close()
                    return token_data
                    
                except Exception as e:
                    logger.error(f"Error scraping {token}: {str(e)}")
                    return None
                    
            # Create tasks for parallel scraping
            tasks = [scrape_token(token) for token in tokens]
            scraped_data = await asyncio.gather(*tasks)
            
            # Filter out None results and add to results list
            results = [data for data in scraped_data if data is not None]
            
            # Sort by growth rate when there are spikes, otherwise by Twitter score
            results.sort(key=lambda x: (
                x['follower_metrics']['is_spiking'],
                x['follower_metrics']['pct_change_1h'],
                x['twitter_stats']['twitter_score']
            ), reverse=True)
            
            await context.close()
            return results, alerts
            
        except Exception as e:
            logger.error(f"Error generating leaderboard: {str(e)}")
            return None, []

    async def _scrape_account_stats_parallel(self, page, username):
        """Scrape account statistics using a specific page"""
        try:
            await page.goto(f'https://twitter.com/{username}', wait_until='domcontentloaded')
            await page.wait_for_selector('[data-testid="UserName"]', timeout=10000)
            
            # Get follower count
            followers_text = await page.evaluate('''() => {
                const elements = document.querySelectorAll('a[href*="/followers"] span span');
                for (const elem of elements) {
                    const text = elem.textContent;
                    if (text && /^[0-9,.KMB]+$/.test(text.trim())) {
                        return text.trim();
                    }
                }
                return '0';
            }''')
            
            followers_count = self._parse_number(followers_text)
            
            # Get bio
            bio = await page.evaluate('''() => {
                const bioElem = document.querySelector('[data-testid="UserDescription"]');
                return bioElem ? bioElem.textContent : '';
            }''')
            
            # Get verification status
            verified = await page.evaluate('''() => {
                return !!document.querySelector('[data-testid="UserName"] svg[aria-label*="Verified"]');
            }''')
            
            # Calculate engagement rate (simplified for parallel processing)
            engagement_rate = 0.001  # Default value
            
            return {
                'username': username,
                'followers_count': followers_count,
                'bio': bio,
                'verified': verified,
                'engagement_rate': engagement_rate,
                'twitter_score': self._calculate_twitter_score(followers_count, engagement_rate, verified)
            }
            
        except Exception as e:
            logger.error(f"Error scraping account stats for {username}: {str(e)}")
            return None

    async def get_market_data(self, tokens):
        """Get market data from Binance API"""
        try:
            # Map Twitter usernames to Binance trading pairs
            symbol_map = {
                'bitcoin': 'BTCUSDT',
                'ethereum': 'ETHUSDT',
                'binance': 'BNBUSDT',
                'dogecoin': 'DOGEUSDT',
                'cardano': 'ADAUSDT',
                'solana': 'SOLUSDT',
                'ripple': 'XRPUSDT',
                'polkadot': 'DOTUSDT',
                'avalanche': 'AVAXUSDT',
                'chainlink': 'LINKUSDT'
            }
            
            market_data = {}
            
            # Handle both single token and list of tokens
            if isinstance(tokens, str):
                tokens = [tokens]
            
            # Fetch data from Binance API
            base_url = "https://api.binance.com/api/v3"
            
            async with aiohttp.ClientSession() as session:
                for token in tokens:
                    try:
                        # Get symbol for the token
                        symbol = symbol_map.get(token.lower())
                        if not symbol:
                            market_data[token] = {
                                'price': 0,
                                'price_change_24h': 0,
                                'market_cap': 0
                            }
                            continue
                        
                        # Get current price
                        price_url = f"{base_url}/ticker/price?symbol={symbol}"
                        async with session.get(price_url) as response:
                            if response.status == 200:
                                price_data = await response.json()
                                price = float(price_data['price'])
                            else:
                                market_data[token] = {
                                    'price': 0,
                                    'price_change_24h': 0,
                                    'market_cap': 0
                                }
                                continue
                        
                        # Get 24h price change and volume
                        stats_url = f"{base_url}/ticker/24hr?symbol={symbol}"
                        async with session.get(stats_url) as response:
                            if response.status == 200:
                                stats_data = await response.json()
                                price_change = float(stats_data['priceChangePercent'])
                                volume = float(stats_data['quoteVolume'])
                                market_cap = volume * price  # Using quote volume as proxy for market cap
                            else:
                                market_data[token] = {
                                    'price': 0,
                                    'price_change_24h': 0,
                                    'market_cap': 0
                                }
                                continue
                        
                        market_data[token] = {
                            'price': price,
                            'price_change_24h': price_change,
                            'market_cap': market_cap
                        }
                        
                    except Exception as e:
                        logger.error(f"Error fetching market data for {token}: {str(e)}")
                        market_data[token] = {
                            'price': 0,
                            'price_change_24h': 0,
                            'market_cap': 0
                        }
            
            return market_data
            
        except Exception as e:
            logger.error(f"Error fetching market data: {str(e)}")
            return {token: {'price': 0, 'price_change_24h': 0, 'market_cap': 0} for token in tokens}

    async def get_twitter_data(self, usernames):
        """Get Twitter data for the given usernames"""
        try:
            twitter_data = {}
            for username in usernames:
                # Scrape Twitter stats
                stats = await self.scrape_account_stats(username)
                if stats:
                    twitter_data[username] = stats
            return twitter_data
        except Exception as e:
            logger.error(f"Error getting Twitter data: {str(e)}")
            return {}

    async def track_follower_changes(self, username, duration_hours=1, interval_minutes=10):
        """Track follower changes using Playwright"""
        try:
            follower_data = []
            intervals = int((duration_hours * 60) / interval_minutes)
            
            for i in range(intervals + 1):
                current_time = datetime.now()
                stats = await self.scrape_account_stats(username)
                
                if stats:
                    follower_data.append({
                        'timestamp': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'followers': stats['followers_count']
                    })
                    
                    if i > 0:
                        initial_followers = follower_data[0]['followers']
                        current_followers = stats['followers_count']
                        if initial_followers > 0:
                            percent_change = ((current_followers - initial_followers) / initial_followers) * 100
                            logger.info(f"Follower change after {i*interval_minutes} minutes: {percent_change:.2f}%")
                
                if i < intervals:
                    await asyncio.sleep(interval_minutes * 60)
            
            return follower_data
                    
        except Exception as e:
            logger.error(f"Error tracking follower changes: {str(e)}")
            return None

    async def close(self):
        """Close the browser and clean up resources"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.error(f"Error closing browser: {str(e)}")
            raise

    async def get_tracked_tokens(self):
        """Get list of tokens/usernames to track"""
        return [
            "ethereum",
            "bitcoin",
            "binance",
            "dogecoin",
            "cardano",
            "solana",
            "ripple",
            "polkadot",
            "avalanche",
            "chainlink"
        ]

def main():
    # Example usage
    scraper = TwitterScraper()
    
    # List of tokens to analyze from the provided list
    tokens = [
        "solana",  # @solana
        "BNBCHAIN",  # @BNBCHAIN
        "arbitrum",  # @arbitrum
        "avalancheavax",  # @avalancheavax
        "0xPolygon",  # @0xPolygon
        "optimismFND",  # @optimismFND
        "Cardano",  # @Cardano
        "Polkadot",  # @Polkadot
        "chainlink",  # @chainlink
        "tezos"  # @tezos
    ]
    
    try:
        # Run live leaderboard with 5-minute updates
        leaderboard_data, alerts = asyncio.run(scraper.generate_leaderboard(tokens))
        
        if leaderboard_data:
            # Print leaderboard
            print("\nTrending Projects by Twitter Score growth\n")
            print(f"{'#':<4} {'Username':<20} {'Followers':<12} {'Change':<8} {'Score':<8} Description\n")
            print("-" * 80)
            
            for i, entry in enumerate(leaderboard_data, 1):
                followers = f"{entry['twitter_stats']['followers_count']:,}"
                change = f"{entry['follower_metrics']['change_24h']:+d}" if entry['follower_metrics']['change_24h'] != 0 else "0"
                score = str(entry['twitter_stats']['twitter_score'])
                
                print(f"{i:<4} {entry['token']:<20} {followers:<12} {change:<8} {score:<8} {entry['twitter_stats']['bio'][:50]}...\n")
            
            # Print alerts
            if alerts:
                print("\nAlerts:")
                for alert in alerts:
                    print(alert)
            
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        try:
            asyncio.run(scraper.close())
        except:
            pass

if __name__ == "__main__":
    main()