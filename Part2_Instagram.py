import feedparser
import pyshorteners
import requests
import pickle
import os
import time
import logging
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap
import random

# Configurations
FEED_URL = "http://rss.cnn.com/rss/edition_world.rss"  # CNN RSS feed
BITLY_API_KEY = "c2752489dd14abe6ac23b9a93c4b878f792f2527"  # Replace with your Bitly API key
ACCESS_TOKEN = "EAA2wPKwMRSEBO7ldCFAyyAYRHcFBR37aVsRdvrbmJSS2GashBdYhRuYlSTNL2shNbivBMw3oy6nZBsZBWBHktBAZCZCTzurLmXXIDrXpnSrRAXT6ZBixeu9nu8ihZBXxgGVZA9OQoZBM94bn3SpBiLfZCMY2kHCZAtlFYbdgYp25u7ZBZAZBuK2GhEZAVT85bg0Y2ZBJx0G"  # Replace with your Instagram Access Token
USER_ID = "17841471034402887"  # Your Instagram Account ID
IMGUR_CLIENT_ID = "202495689ba3db5"  # Replace with your Imgur client ID

# Logging configuration
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('rss_instagram_poster.log'),
        logging.StreamHandler()
    ]
)

# Persistent storage for processed entries
PROCESSED_ENTRIES_FILE = 'processed_entries.pkl'

def load_processed_entries():
    """Load processed entry links from a pickle file."""
    try:
        # Check if file exists and is not empty
        if os.path.exists(PROCESSED_ENTRIES_FILE) and os.path.getsize(PROCESSED_ENTRIES_FILE) > 0:
            with open(PROCESSED_ENTRIES_FILE, 'rb') as f:
                loaded_entries = pickle.load(f)
                return set(loaded_entries) if loaded_entries else set()
        else:
            # Create an empty file if it doesn't exist
            with open(PROCESSED_ENTRIES_FILE, 'wb') as f:
                pickle.dump([], f)
            return set()
    except (FileNotFoundError, EOFError, pickle.UnpicklingError):
        # Handle various potential errors
        logging.warning("Could not load processed entries. Creating a new set.")
        return set()

def save_processed_entries(processed_entries):
    """Save processed entry links to a pickle file."""
    try:
        with open(PROCESSED_ENTRIES_FILE, 'wb') as f:
            # Limit the number of processed entries to prevent the file from growing too large
            pickle.dump(list(processed_entries)[-1000:], f)
    except Exception as e:
        logging.error(f"Failed to save processed entries: {e}")

def shorten_url(url):
    """Shorten URLs using Bitly."""
    try:
        s = pyshorteners.Shortener(api_key=BITLY_API_KEY)
        return s.bitly.short(url)
    except Exception as e:
        logging.error(f"URL shortening failed: {e}")
        return url

def generate_caption(article_title, article_summary, article_url):
    """Generate a caption for Instagram post."""
    try:
        shortened_url = shorten_url(article_url)
        return f"Breaking news: {article_title} - {article_summary[:200]}... Read more: {shortened_url}"
    except Exception as e:
        logging.error(f"Caption generation failed: {e}")
        return f"{article_title} - Read more at {article_url}"

def generate_image(article_title, article_summary):
    """Generate a custom image based on article details."""
    try:
        width, height = 1080, 1080  # Instagram recommended size
        background_colors = [
            (240, 248, 255),  # AliceBlue
            (240, 255, 240),  # Honeydew
            (255, 250, 240),  # FloralWhite
            (248, 248, 255),  # GhostWhite
        ]
        
        # Create image
        image = Image.new('RGB', (width, height), color=random.choice(background_colors))
        draw = ImageDraw.Draw(image)
        
        # Font setup
        try:
            font_paths = [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "C:\\Windows\\Fonts\\arialbd.ttf",
            ]
            font_path = next(path for path in font_paths if os.path.exists(path))
            title_font = ImageFont.truetype(font_path, 50)
            summary_font = ImageFont.truetype(font_path, 30)
        except Exception:
            title_font = ImageFont.load_default()
            summary_font = ImageFont.load_default()
        
        # Draw title
        wrapped_title = textwrap.wrap(article_title, width=25)
        y_text = 100
        for line in wrapped_title:
            draw.text((50, y_text), line, fill=(0, 0, 0), font=title_font)
            y_text += 60
        
        # Draw summary
        wrapped_summary = textwrap.wrap(article_summary, width=40)
        y_text += 50
        for line in wrapped_summary:
            draw.text((50, y_text), line, fill=(50, 50, 50), font=summary_font)
            y_text += 40
            if y_text > height - 200:
                break
        
        # Add decorative elements
        for _ in range(15):
            x1, y1 = random.randint(0, width), random.randint(0, height)
            x2, y2 = x1 + random.randint(10, 50), y1 + random.randint(10, 50)
            draw.line([x1, y1, x2, y2], fill=(200, 200, 255), width=2)
        
        return image
    except Exception as e:
        logging.error(f"Image generation failed: {e}")
        return None

def upload_photo_to_imgur(image):
    """Upload image to Imgur."""
    try:
        imgur_url = "https://api.imgur.com/3/image"
        headers = {"Authorization": f"Client-ID {IMGUR_CLIENT_ID}"}
        
        img_buffer = BytesIO()
        image.save(img_buffer, format='JPEG')
        img_buffer.seek(0)
        
        response = requests.post(imgur_url, headers=headers, files={'image': img_buffer})
        response_data = response.json()
        
        if response_data['success']:
            image_url = response_data['data']['link']
            logging.info(f"Image uploaded to Imgur: {image_url}")
            return image_url
        else:
            logging.error(f"Imgur upload failed: {response_data}")
            return None
    except Exception as e:
        logging.error(f"Imgur upload error: {e}")
        return None

def upload_photo_to_instagram(image_url, caption):
    """Upload photo to Instagram."""
    try:
        upload_url = f"https://graph.facebook.com/v16.0/{USER_ID}/media"
        payload = {
            "image_url": image_url,
            "caption": caption,
            "access_token": ACCESS_TOKEN,
        }
        response = requests.post(upload_url, data=payload)
        response_data = response.json()
        
        if "id" in response_data:
            logging.info(f"Photo uploaded to Instagram. Media ID: {response_data['id']}")
            return response_data["id"]
        else:
            logging.error(f"Instagram upload failed: {response_data}")
            return None
    except Exception as e:
        logging.error(f"Instagram upload error: {e}")
        return None

def publish_photo(media_id):
    """Publish photo on Instagram."""
    try:
        publish_url = f"https://graph.facebook.com/v16.0/{USER_ID}/media_publish"
        payload = {
            "creation_id": media_id,
            "access_token": ACCESS_TOKEN,
        }
        response = requests.post(publish_url, data=payload)
        response_data = response.json()
        
        if "id" in response_data:
            logging.info(f"Photo published on Instagram. Post ID: {response_data['id']}")
            return True
        else:
            logging.error(f"Instagram publish failed: {response_data}")
            return False
    except Exception as e:
        logging.error(f"Instagram publish error: {e}")
        return False

def monitor_rss_feed(check_interval=300, max_entries_per_run=5):
    """
    Continuously monitor RSS feed for new entries.
    
    :param check_interval: Time between RSS feed checks (in seconds)
    :param max_entries_per_run: Maximum number of new entries to process in each run
    """
    processed_entries = load_processed_entries()
    
    while True:
        try:
            # Parse RSS feed
            feed = feedparser.parse(FEED_URL)
            logging.info(f"Checking RSS feed: {FEED_URL}")
            
            # Counter to limit entries processed in one run
            entries_processed = 0
            
            for entry in feed.entries:
                # Skip already processed entries
                if entry.link in processed_entries:
                    continue
                
                # Extract article details
                article_title = entry.title
                article_summary = entry.get('summary', entry.get('description', 'No summary available'))
                article_url = entry.link
                
                # Generate caption
                caption = generate_caption(article_title, article_summary, article_url)
                logging.info(f"Processing article: {article_title}")
                
                # Generate image
                image = generate_image(article_title, article_summary)
                
                if image:
                    # Upload to Imgur
                    image_url = upload_photo_to_imgur(image)
                    
                    if image_url:
                        # Upload to Instagram
                        media_id = upload_photo_to_instagram(image_url, caption)
                        
                        if media_id:
                            # Publish on Instagram
                            if publish_photo(media_id):
                                # Mark as processed
                                processed_entries.add(entry.link)
                                save_processed_entries(processed_entries)
                                
                                entries_processed += 1
                                
                                # Stop if max entries processed
                                if entries_processed >= max_entries_per_run:
                                    break
                
            # Wait before next check
            logging.info(f"Waiting {check_interval} seconds before next check")
            time.sleep(check_interval)
        
        except Exception as e:
            logging.error(f"An error occurred in RSS monitoring: {e}")
            # Wait before retrying
            time.sleep(check_interval)

if __name__ == "__main__":
    logging.info("RSS to Instagram Poster started")
    try:
        # Check and validate configurations
        if not all([BITLY_API_KEY, ACCESS_TOKEN, USER_ID, IMGUR_CLIENT_ID]):
            logging.error("Please configure all API keys and tokens before running")
        else:
            monitor_rss_feed()
    except KeyboardInterrupt:
        logging.info("RSS to Instagram Poster stopped by user")