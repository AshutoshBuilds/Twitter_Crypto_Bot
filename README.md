# Twitter Score Leaderboard

A Python-based web application that tracks and displays Twitter metrics for cryptocurrency projects, featuring real-time updates and a modern web interface.

## Features

- Live Twitter metrics tracking
- Real-time leaderboard updates
- Modern, responsive web interface
- Multiple time interval views (3d/week/month)
- Automatic data updates
- REST API endpoints
- Detailed analytics and engagement metrics

## Project Structure

```
.
├── src/                  # Source code
│   ├── app.py           # Flask web application
│   ├── static/          # Static files (CSS, JS, images)
│   ├── templates/       # HTML templates
│   │   └── index.html   # Main leaderboard template
│   ├── utils/           # Utility functions
│   │   ├── __init__.py
│   │   └── twitter_scraper.py
│   ├── data/            # Data storage
│   └── logs/            # Application logs
├── config/              # Configuration files
│   ├── requirements.txt # Project dependencies
│   └── .env            # Environment variables
├── tests/               # Test files
└── README.md           # Project documentation
```

## Requirements

- Python 3.8+
- Chrome browser (for web scraping)
- Virtual environment (recommended)

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd Twitter
```

2. Create and activate a virtual environment:
```bash
python -m venv twitter_env
source twitter_env/bin/activate  # On Windows: twitter_env\Scripts\activate
```

3. Install required packages:
```bash
pip install -r config/requirements.txt
```

4. Set up environment variables in `config/.env`:
```
TWITTER_USERNAME=your_username
TWITTER_PASSWORD=your_password
```

## Usage

### Running the Web Interface

1. Start the Flask application:
```bash
python src/app.py
```

2. Open your browser and navigate to:
```
http://localhost:5000
```

The web interface will automatically:
- Update every 5 minutes
- Show real-time follower changes
- Display Twitter scores
- Track engagement metrics

### API Endpoints

1. Get Current Leaderboard:
```
GET /api/leaderboard
```

Response format:
```json
{
    "timestamp": "2025-01-31 12:34:56",
    "data": [
        {
            "username": "bitcoin",
            "followers": 1234567,
            "follower_change": 1000,
            "twitter_score": 500,
            "description": "..."
        },
        ...
    ]
}
```

### Customization

1. Modify tracked tokens in `src/app.py`:
```python
tokens = [
    "ethereum",
    "bitcoin",
    # Add more tokens...
]
```

2. Adjust update frequency:
```python
# In src/app.py
time.sleep(300)  # 5 minutes

# In src/templates/index.html
setInterval(refreshLeaderboard, 300000);  # 5 minutes
```

## Features

### Web Interface
- Dark theme design
- Real-time updates
- Interactive refresh
- Time interval selection
- Formatted numbers (K/M)
- Color-coded changes
- Responsive layout

### Data Collection
- Follower count tracking
- Engagement metrics
- Tweet analysis
- Hashtag monitoring
- Verification status

### Analytics
- Twitter Score calculation
- Engagement rate analysis
- Trend tracking
- Historical data storage

### Data Storage
- JSON files in `src/data/`
- CSV exports available
- Historical tracking
- Backup functionality

### Database
- SQLite database for persistent storage
- Stores historical follower counts
- Enables tracking of follower changes over time
- Automated daily backups
- Schema includes:
  - User profiles
  - Follower history
  - Engagement metrics
  - Timestamp tracking
- Efficient querying for trend analysis
- Data retention policies

### Logging
- Detailed logs in `src/logs/`
- Error tracking
- Performance monitoring
- Activity history

## Development

### Running Tests
```bash
python -m pytest tests/
```

### Code Style
We follow PEP 8 guidelines for Python code. Run linting with:
```bash
flake8 src/
```

## Author

Ashutosh Shukla
Email: ashutoshshukla734.as@gmail.com

## License

This project is licensed under the MIT License - see the LICENSE file for details.