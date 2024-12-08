import requests
import os
import webbrowser
from urllib.parse import urlencode
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import threading
import feedparser
import pyshorteners
import pickle
import time
import logging
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import textwrap

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('wordpress_rss_publisher.log'),
        logging.StreamHandler()
    ]
)

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handles the OAuth callback and extracts the authorization code."""
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        
        query_components = parse_qs(urlparse(self.path).query)
        
        if 'code' in query_components:
            self.server.auth_code = query_components['code'][0]
            response_html = """
            <html>
                <body style='font-family: Arial, sans-serif; text-align: center; padding: 50px;'>
                    <h1 style='color: #4CAF50;'>Authorization Successful!</h1>
                    <p>You can close this window now.</p>
                </body>
            </html>"""
        else:
            self.server.auth_code = None
            response_html = """
            <html>
                <body style='font-family: Arial, sans-serif; text-align: center; padding: 50px;'>
                    <h1 style='color: #f44336;'>Authorization Failed!</h1>
                    <p>No authorization code received. Please try again.</p>
                </body>
            </html>"""
            
        self.wfile.write(response_html.encode())
        
    def log_message(self, format, *args):
        """Suppress logging of HTTP requests."""
        return

class WordPressRSSPublisher:
    """Manages RSS feed monitoring and publishing to a WordPress site."""
    def __init__(self, site_url, client_id, client_secret, feed_url, bitly_api_key=None, processed_entries_file='processed_entries.pkl'):
        """
        Initializes the publisher with the required configuration.

        Args:
            site_url (str): WordPress site URL.
            client_id (str): OAuth client ID.
            client_secret (str): OAuth client secret.
            feed_url (str): RSS feed URL.
            bitly_api_key (str, optional): Bitly API key for URL shortening.
            processed_entries_file (str): Path to the file storing processed entries.
        """
        self.site_url = site_url.replace('https://', '').replace('http://', '').rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.api_base = f"https://public-api.wordpress.com/rest/v1.1/sites/{self.site_url}"
        self.redirect_uri = "http://localhost:8080"
        
        # RSS Feed configuration
        self.feed_url = feed_url
        self.bitly_api_key = bitly_api_key
        self.processed_entries_file = processed_entries_file
        self.processed_entries = self.load_processed_entries()

    def get_authorization_url(self):
        """
        Generates the OAuth authorization URL.

        Returns:
            str: Authorization URL.
        """
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': 'posts media',
        }
        return f"https://public-api.wordpress.com/oauth2/authorize?{urlencode(params)}"

    def wait_for_callback(self, timeout=120):
        """
        Waits for the OAuth callback and extracts the authorization code.

        Args:
            timeout (int): Timeout in seconds for waiting.

        Returns:
            str: Authorization code, or None if timeout occurs.
        """
        server = HTTPServer(('localhost', 8080), OAuthCallbackHandler)
        server.timeout = timeout
        server.auth_code = None
        
        response_received = threading.Event()
        
        def handle_request():
            try:
                server.handle_request()
                response_received.set()
            except Exception as e:
                logging.error(f"Error handling callback: {e}")
                server.auth_code = None
                response_received.set()
        
        server_thread = threading.Thread(target=handle_request)
        server_thread.daemon = True
        server_thread.start()
        
        if not response_received.wait(timeout):
            logging.error("Timeout waiting for authorization response")
            return None
        
        return server.auth_code

    def authenticate(self, auth_code):
        """
        Exchanges the authorization code for an access token.

        Args:
            auth_code (str): Authorization code.

        Returns:
            bool: True if authentication is successful, False otherwise.
        """
        token_url = "https://public-api.wordpress.com/oauth2/token"
        data = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'code': auth_code,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri
        }

        try:
            response = requests.post(token_url, data=data)
            if response.status_code == 200:
                self.access_token = response.json()['access_token']
                logging.info("Authentication successful!")
                return True
            else:
                logging.error(f"Authentication failed: {response.status_code}")
                logging.error(f"Error: {response.text}")
                return False
        except Exception as e:
            logging.error(f"Authentication error: {str(e)}")
            return False

    def load_processed_entries(self):
        """
        Loads the processed entries from a file.

        Returns:
            set: Set of processed entry URLs.
        """
        try:
            if os.path.exists(self.processed_entries_file) and os.path.getsize(self.processed_entries_file) > 0:
                with open(self.processed_entries_file, 'rb') as f:
                    return set(pickle.load(f))
            return set()
        except Exception:
            logging.warning("Failed to load processed entries. Starting fresh.")
            return set()

    def save_processed_entries(self):
        """Saves the processed entries to a file."""
        try:
            with open(self.processed_entries_file, 'wb') as f:
                pickle.dump(list(self.processed_entries), f)
        except Exception as e:
            logging.error(f"Failed to save processed entries: {e}")

    def shorten_url(self, url):
        """
        Shortens a URL using Bitly API.

        Args:
            url (str): URL to shorten.

        Returns:
            str: Shortened URL, or original URL if shortening fails.
        """
        if not self.bitly_api_key:
            return url
            
        try:
            shortener = pyshorteners.Shortener(api_key=self.bitly_api_key)
            return shortener.bitly.short(url)
        except Exception as e:
            logging.error(f"URL shortening failed: {e}")
            return url

    def generate_image(self, article_title, article_summary):
        """
        Generates an image containing the article title and summary.

        Args:
            article_title (str): Article title.
            article_summary (str): Article summary.

        Returns:
            Image: PIL Image object containing the article text.
        """
        try:
            width, height = 1200, 630
            image = Image.new('RGB', (width, height), color=(255, 255, 255))
            draw = ImageDraw.Draw(image)
            
            try:
                title_font = ImageFont.truetype("arial.ttf", 40)
                summary_font = ImageFont.truetype("arial.ttf", 30)
            except:
                title_font = ImageFont.load_default()
                summary_font = ImageFont.load_default()

            y_offset = 50
            for line in textwrap.wrap(article_title, width=30):
                draw.text((50, y_offset), line, fill=(0, 0, 0), font=title_font)
                y_offset += 50
            
            y_offset += 20
            summary_text = article_summary[:500] + "..." if len(article_summary) > 500 else article_summary
            for line in textwrap.wrap(summary_text, width=40):
                draw.text((50, y_offset), line, fill=(50, 50, 50), font=summary_font)
                y_offset += 30
                if y_offset > height - 50:
                    break

            return image
        except Exception as e:
            logging.error(f"Image generation failed: {e}")
            return None

    def upload_media(self, image):
        """
        Uploads an image to WordPress as a media file.

        Args:
            image (Image): PIL Image object to upload.

        Returns:
            int: Media ID of the uploaded image, or None if upload fails.
        """
        if not self.access_token:
            logging.error("No access token available. Please authenticate first.")
            return None

        try:
            headers = {
                "Authorization": f"Bearer {self.access_token}",
            }
            
            img_buffer = BytesIO()
            image.save(img_buffer, format='JPEG', quality=85)
            img_buffer.seek(0)

            files = {'media[]': ('image.jpg', img_buffer, 'image/jpeg')}
            response = requests.post(
                f"{self.api_base}/media/new",
                headers=headers,
                files=files
            )

            if response.status_code == 200:
                media_data = response.json()['media'][0]
                logging.info(f"Image uploaded to WordPress: {media_data['URL']}")
                return media_data['ID']
            else:
                logging.error(f"Failed to upload image: {response.status_code}")
                logging.error(f"Error message: {response.text}")
                return None

        except Exception as e:
            logging.error(f"Error uploading media: {str(e)}")
            return None

    def publish_post(self, title, content, featured_media_id=None):
        """
        Publishes a post on WordPress.

        Args:
            title (str): Post title.
            content (str): Post content.
            featured_media_id (int, optional): Media ID for the featured image.

        Returns:
            str: URL of the published post, or None if publishing fails.
        """
        if not self.access_token:
            logging.error("No access token available. Please authenticate first.")
            return None

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        post_data = {
            'title': title,
            'content': content,
            'status': 'publish'
        }

        if featured_media_id:
            post_data['featured_image'] = str(featured_media_id)

        try:
            response = requests.post(
                f"{self.api_base}/posts/new",
                json=post_data,
                headers=headers
            )

            if response.status_code == 200:
                post_data = response.json()
                logging.info(f"Post published successfully: {post_data['URL']}")
                return post_data['URL']
            else:
                logging.error(f"Failed to publish post: {response.status_code}")
                logging.error(f"Error message: {response.text}")
                return None

        except Exception as e:
            logging.error(f"Error publishing post: {str(e)}")
            return None

    def process_feed(self):
        """
        Processes the RSS feed and publishes new articles to WordPress.
        """
        try:
            feed = feedparser.parse(self.feed_url)
            if 'entries' not in feed:
                logging.warning("No entries found in the RSS feed.")
                return
            
            new_entries = [entry for entry in feed.entries if entry.link not in self.processed_entries]

            for entry in new_entries:
                print(entry)
                
                title = entry.title
                
                summary = entry.summary if 'summary' in entry else entry.description if 'description' in entry else None
                
                # If neither summary nor description exists, skip this entry
                if not summary:
                    continue
                url = entry.link
                print(f"Title: {title}")
                print(f"Summary: {summary}")
                print(f"URL: {url}")
                short_url = self.shorten_url(url)
                content = f"<p>{summary}</p><p><a href='{short_url}'>Read more</a></p>"
                image = self.generate_image(title, summary)
                media_id = self.upload_media(image) if image else None
                post_url = self.publish_post(title, content, media_id)
                
                if post_url:
                    self.processed_entries.add(entry.link)
                    self.save_processed_entries()
        except Exception as e:
            logging.error(f"Error processing feed: {e}")

# Usage example
if __name__ == "__main__":
    site_url = "zee915.wordpress.com"
    client_id = "110048"
    client_secret = "WZmO0zHvfIaU8q69kvf2ImQ035hnPlTUWQQMxhQwaQ91WATcxPxx5LEz6U5i7Han"
    feed_url = "http://rss.cnn.com/rss/edition_world.rss"  # Example RSS feed
    bitly_api_key = "c2752489dd14abe6ac23b9a93c4b878f792f2527"  
    
    publisher = WordPressRSSPublisher(site_url, client_id, client_secret, feed_url, bitly_api_key)
    
    auth_url = publisher.get_authorization_url()
    logging.info(f"Open the following URL in your browser to authenticate: {auth_url}")
    webbrowser.open(auth_url)
    
    auth_code = publisher.wait_for_callback()
    if auth_code and publisher.authenticate(auth_code):
        while True:
            publisher.process_feed()
            time.sleep(600)  # Poll every 10 minutes
