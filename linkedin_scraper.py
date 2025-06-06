import os
import time
import random
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse
from dotenv import load_dotenv
from fake_useragent import UserAgent
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException
)
from bs4 import BeautifulSoup
from selenium.webdriver.common.keys import Keys
from openai import OpenAI
import requests
import json
import base64
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import sys
from config import (
    GENERAL_DELAYS,
    LOGIN_DELAYS,
    SEARCH_DELAYS,
    SCROLL_DELAYS,
    PROXY_DELAYS,
    ERROR_DELAYS,
    JOB_PROCESSING_DELAYS,
    SESSION_DELAYS,
    MOUSE_DELAYS,
    TIMEOUTS,
    RETRY_CONFIG
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class LinkedInScraper:
    def __init__(self):
        """Initialize the LinkedIn scraper with configuration."""
        load_dotenv()
        self.email = os.getenv('LINKEDIN_EMAIL')
        self.password = os.getenv('LINKEDIN_PASSWORD')
        self.base_url = "https://www.linkedin.com"
        self.jobs_url = f"{self.base_url}/jobs"
        self.driver = None
        self.ua = UserAgent()
        self.openai_client = OpenAI(api_key="your_api_key")
        
        # ProxyMesh configuration
        self.proxy_username = "yourusername"
        self.proxy_password = "yourpassword"
        self.proxy_list = [
            "proxy_1",
            "proxy_2"
        ]
        self.current_proxy_index = 0
        self.proxy_rotation_interval = random.randint(100, 150)  # Rotate every 100-150 jobs
        
        # MongoDB configuration
        try:
            logger.info("Initializing MongoDB connection...")
            self.mongo_client = MongoClient('mongodb://localhost:27017/', serverSelectionTimeoutMS=5000)
            self.db = self.mongo_client['linkedin_jobs']
            self.collection = self.db['jobdetails']
            self.search_criteria_collection = self.db['search_criteria']
            
            # Check MongoDB connection
            if not self.check_mongodb_connection():
                raise Exception("Failed to connect to MongoDB")
            
            # Create indexes
            self.collection.create_index("job_id", unique=True)
            self.collection.create_index("search_id")
            self.search_criteria_collection.create_index([("job_title", 1), ("location", 1), ("software", 1)], unique=True)
            logger.info("MongoDB indexes created successfully")
                
        except Exception as e:
            logger.error(f"MongoDB initialization failed: {str(e)}")
            raise
        
        self.setup_driver()

    def check_mongodb_connection(self):
        """Check MongoDB connection and collection."""
        try:
            # Test connection
            self.mongo_client.admin.command('ping')
            logger.info("MongoDB connection successful")
            
            # Test collection
            try:
                self.collection.find_one()
                logger.info("MongoDB collection access successful")
            except Exception as e:
                logger.error(f"Failed to access collection: {str(e)}")
                return False
            
            # Drop existing indexes to avoid conflicts
            try:
                self.collection.drop_indexes()
                logger.info("Dropped existing indexes")
            except Exception as e:
                logger.error(f"Failed to drop indexes: {str(e)}")
                return False
            
            # Create new indexes with correct field names
            try:
                self.collection.create_index("job_id", unique=True)
                self.collection.create_index("search_id")
                logger.info("MongoDB indexes created/verified")
            except Exception as e:
                logger.error(f"Failed to create indexes: {str(e)}")
                return False
            
            return True
        except ConnectionFailure as e:
            logger.error(f"MongoDB connection failed: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error checking MongoDB connection: {str(e)}")
            return False

    def get_next_proxy(self):
        """Get the next proxy from the rotation."""
        proxy = self.proxy_list[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
        return proxy

    def setup_driver(self):
        """Configure and initialize the Chrome WebDriver with proxy."""
        chrome_options = Options()
        # chrome_options.add_argument('--headless')  # Removed headless mode
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('--disable-notifications')
        chrome_options.add_argument('--disable-popup-blocking')
        chrome_options.add_argument('--start-maximized')
        
        # Get rotated headers
        headers = self.rotate_headers()
        chrome_options.add_argument(f'user-agent={headers["User-Agent"]}')
        
        # Add additional headers
        chrome_options.add_argument(f'--accept-language={headers["Accept-Language"]}')
        chrome_options.add_argument(f'--accept={headers["Accept"]}')
        
        # Setup proxy with authentication
        proxy = self.get_next_proxy()
        
        # Create a proxy extension
        manifest_json = """
        {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Chrome Proxy",
            "permissions": [
                "proxy",
                "tabs",
                "unlimitedStorage",
                "storage",
                "webRequest",
                "webRequestBlocking"
            ],
            "background": {
                "scripts": ["background.js"]
            }
        }
        """

        background_js = """
        var config = {
            mode: "fixed_servers",
            rules: {
                singleProxy: {
                    scheme: "http",
                    host: "%s",
                    port: %s
                },
                bypassList: []
            }
        };

        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

        function callbackFn(details) {
            return {
                authCredentials: {
                    username: "%s",
                    password: "%s"
                }
            };
        }

        chrome.webRequest.onAuthRequired.addListener(
            callbackFn,
            {urls: ["<all_urls>"]},
            ['blocking']
        );
        """ % (
            proxy.split(':')[0],
            proxy.split(':')[1],
            self.proxy_username,
            self.proxy_password
        )

        # Create proxy extension directory
        import os
        import zipfile
        import tempfile

        plugin_dir = os.path.join(tempfile.gettempdir(), 'proxy_auth_plugin')
        if not os.path.exists(plugin_dir):
            os.mkdir(plugin_dir)

        with open(os.path.join(plugin_dir, "manifest.json"), "w") as f:
            f.write(manifest_json)
        with open(os.path.join(plugin_dir, "background.js"), "w") as f:
            f.write(background_js)

        # Create proxy extension
        plugin_path = os.path.join(plugin_dir, "proxy_auth_plugin.zip")
        with zipfile.ZipFile(plugin_path, 'w') as zp:
            zp.write(os.path.join(plugin_dir, "manifest.json"), "manifest.json")
            zp.write(os.path.join(plugin_dir, "background.js"), "background.js")

        # Add proxy extension to Chrome options
        chrome_options.add_extension(plugin_path)
        
        # Use local ChromeDriver from drivers folder
        driver_path = os.path.join('drivers', 'chromedriver')
        service = Service(executable_path=driver_path)
        self.driver = webdriver.Chrome(service=service, options=chrome_options)
        self.driver.maximize_window()

    def calculate_posted_date(self, date_text: str) -> str:
        """Calculate the actual posted date based on the relative time text."""
        try:
            current_date = datetime.now()
            
            # Handle special cases
            if 'reposted' in date_text.lower():
                return date_text.strip()  # Keep as is for reposted jobs
                
            if 'month' in date_text.lower() or 'week' in date_text.lower():
                return date_text.strip()  # Keep as is for months and weeks
                
            # Extract the number and unit
            parts = date_text.lower().split()
            if len(parts) >= 2:
                try:
                    number = int(parts[0])
                    unit = parts[1]
                    
                    if 'hour' in unit:
                        posted_date = current_date - timedelta(hours=number)
                    elif 'day' in unit:
                        posted_date = current_date - timedelta(days=number)
                    else:
                        return date_text.strip()
                        
                    return posted_date.strftime('%Y-%m-%d')
                except ValueError:
                    # If we can't convert to int, return the original text
                    return date_text.strip()
            
            return date_text.strip()
        except Exception as e:
            logger.error(f"Error calculating posted date: {str(e)}")
            return date_text.strip()

    def print_job_details(self, job_data: Dict):
        """Print job details to terminal in JSON format."""
        # Create a clean copy of job_data without any None values
        clean_job_data = {k: v for k, v in job_data.items() if v is not None}
        
        # Convert to JSON with proper formatting
        json_output = json.dumps(clean_job_data, indent=2)
        
        print("\n" + "="*80)
        print("Job Details:")
        print(json_output)
        print("="*80 + "\n")

    def random_delay(self, min_seconds: float = None, max_seconds: float = None):
        """Add random delay with natural patterns to mimic human behavior."""
        if min_seconds is None:
            min_seconds = GENERAL_DELAYS['min_base_delay']
        if max_seconds is None:
            max_seconds = GENERAL_DELAYS['max_base_delay']
        
        # Base delay with some randomness
        base_delay = random.uniform(min_seconds, max_seconds)
        
        # Occasionally add longer delays to mimic human behavior
        if random.random() < 0.2:  # 20% chance
            base_delay *= random.uniform(
                GENERAL_DELAYS['multiplier_min'],
                GENERAL_DELAYS['multiplier_max']
            )
        
        # Add small random variations
        base_delay += random.uniform(
            GENERAL_DELAYS['additional_delay_min'],
            GENERAL_DELAYS['additional_delay_max']
        )
        
        # Occasionally add longer pauses
        if random.random() < 0.1:  # 10% chance
            base_delay += random.uniform(
                GENERAL_DELAYS['long_additional_delay_min'],
                GENERAL_DELAYS['long_additional_delay_max']
            )
        
        time.sleep(base_delay)

    def manage_session(self):
        """Manage session duration and breaks to mimic human behavior."""
        # Random session duration between 30-60 minutes
        session_duration = random.randint(30, 60)
        
        # Random number of jobs to process per session (20-40)
        jobs_per_session = random.randint(20, 40)
        
        # Random pause duration between jobs (5-15 minutes)
        pause_duration = random.randint(5, 15)
        
        return {
            'session_duration': session_duration,
            'jobs_per_session': jobs_per_session,
            'pause_duration': pause_duration
        }

    def natural_scroll(self, element=None):
        """Implement smooth scrolling with random pauses to mimic human behavior."""
        try:
            if element:
                # Scroll element into view with smooth behavior
                self.driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)
            else:
                # Get page height
                page_height = self.driver.execute_script("return document.body.scrollHeight")
                
                # Start from current position
                current_position = self.driver.execute_script("return window.pageYOffset")
                
                # Scroll in chunks with random pauses
                while current_position < page_height:
                    # Random scroll amount
                    scroll_amount = random.randint(300, 700)
                    current_position += scroll_amount
                    
                    # Smooth scroll to position
                    self.driver.execute_script(f"window.scrollTo({{top: {current_position}, behavior: 'smooth'}});")
                    
                    # Random pause between scrolls
                    time.sleep(random.uniform(0.5, 2))
                    
                    # Occasionally pause longer (20% chance)
                    if random.random() < 0.2:
                        time.sleep(random.uniform(2, 4))
                        
        except Exception as e:
            logger.error(f"Error during natural scrolling: {str(e)}")

    def rotate_headers(self):
        """Rotate request headers to mimic different browsers and devices."""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15'
        ]
        
        headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        }
        
        return headers

    def login(self):
        """Login to LinkedIn with intelligent captcha/OTP handling."""
        try:
            self.driver.get(self.base_url)
            self.random_delay(5, 8)  # Increased initial delay

            # Try to find and close any popups first
            try:
                # Wait for any popups and close them
                popup_close_buttons = self.driver.find_elements(By.CSS_SELECTOR, "button[aria-label='Dismiss']")
                for button in popup_close_buttons:
                    try:
                        button.click()
                        self.random_delay(1, 2)
                    except:
                        pass
            except:
                pass

            # Try to find the sign-in link directly
            try:
                sign_in_link = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='login']"))
                )
                sign_in_link.click()
            except:
                # If direct link not found, try the button
                try:
                    sign_in_button = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CLASS_NAME, "nav__button-secondary"))
                    )
                    # Scroll the button into view
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", sign_in_button)
                    self.random_delay(1, 2)
                    # Try JavaScript click if regular click fails
                    try:
                        sign_in_button.click()
                    except:
                        self.driver.execute_script("arguments[0].click();", sign_in_button)
                except:
                    # If both methods fail, try going directly to login page
                    self.driver.get("https://www.linkedin.com/login")
            
            self.random_delay(3, 5)

            # Enter email
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "username"))
            )
            email_field.clear()
            email_field.send_keys(self.email)
            self.random_delay(1, 2)

            # Enter password
            password_field = self.driver.find_element(By.ID, "password")
            password_field.clear()
            password_field.send_keys(self.password)
            self.random_delay(1, 2)

            # Click sign in
            sign_in_submit = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            try:
                sign_in_submit.click()
            except:
                self.driver.execute_script("arguments[0].click();", sign_in_submit)

            # Wait for verification (captcha and/or OTP)
            print("\nWaiting for verification...")
            print("Please complete any captcha and enter OTP if prompted...")
            
            # Maximum wait time for verification (10 minutes)
            max_wait_time = 600
            start_time = time.time()
            verification_completed = False
            
            while time.time() - start_time < max_wait_time and not verification_completed:
                try:
                    # Check for actual captcha elements with more specific selectors
                    captcha_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                        "iframe[title*='captcha'], div[class*='captcha'], div[class*='challenge'], div[class*='recaptcha']")
                    
                    # Check for OTP input with more specific selectors
                    otp_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                        "input[type='text'][aria-label*='verification'], input[type='text'][aria-label*='code'], input[type='text'][aria-label*='OTP']")
                    
                    # Only print captcha message if we actually find a captcha element
                    if captcha_elements and any(elem.is_displayed() for elem in captcha_elements):
                        print("Captcha detected. Please complete the captcha...")
                        time.sleep(10)  # Wait longer for captcha completion
                        continue
                    
                    if otp_elements and any(elem.is_displayed() for elem in otp_elements):
                        print("OTP verification required. Please enter the OTP...")
                        time.sleep(10)  # Wait longer for OTP entry
                        continue
                    
                    # Check for various success indicators
                    success_indicators = [
                        "div[data-test-id='nav-search-typeahead']",  # Search bar
                        "div[data-test-id='nav-search']",  # Alternative search bar
                        "div[data-test-id='nav-home']",  # Home feed
                        "div[data-test-id='nav-jobs']",  # Jobs section
                        "div[data-test-id='nav-messaging']",  # Messaging section
                        "div[data-test-id='nav-notifications']",  # Notifications
                        "div[data-test-id='nav-profile']"  # Profile
                    ]
                    
                    for indicator in success_indicators:
                        try:
                            element = WebDriverWait(self.driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, indicator))
                            )
                            if element.is_displayed():
                                logger.info("Successfully logged in to LinkedIn")
                                print("Successfully logged in to LinkedIn")
                                verification_completed = True
                                break
                        except:
                            continue
                    
                    if verification_completed:
                        break
                    
                    # Check if we're still on the login page
                    if "login" in self.driver.current_url.lower():
                        time.sleep(5)  # Wait longer between checks
                        continue
                    
                    # If we're not on login page and no success indicators found,
                    # we might be on a different page but still logged in
                    if "linkedin.com" in self.driver.current_url.lower():
                        # Try to navigate to jobs page
                        try:
                            self.driver.get(self.jobs_url)
                            self.random_delay(3, 5)
                            # Verify we're on jobs page
                            if "jobs" in self.driver.current_url.lower():
                                logger.info("Successfully logged in and navigated to jobs page")
                                print("Successfully logged in and navigated to jobs page")
                                verification_completed = True
                                break
                        except:
                            pass
                        
                except Exception as e:
                    time.sleep(5)  # Wait longer between checks
                    continue
            
            if not verification_completed:
                logger.error("Login verification timeout")
                print("Login verification timeout - please check if you're logged in manually")
                return False

            # Additional delay after successful login
            self.random_delay(5, 10)
            return True

        except Exception as e:
            logger.error(f"Failed to login: {str(e)}")
            print(f"Failed to login: {str(e)}")
            return False

    def search_jobs(self, job_title: str, location: str, software: str = None) -> str:
        """Navigate to jobs search page and input search parameters."""
        try:
            # Navigate to jobs page
            self.driver.get(self.jobs_url)
            self.random_delay(3, 5)

            # Combine software and role for search if software is provided, with a comma between them
            search_query = f"{software}, {job_title}" if software else job_title

            # Wait for and fill job title with retry mechanism
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    # Wait for the search field to be present and clickable
                    title_field = WebDriverWait(self.driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[aria-label='Search by title, skill, or company']"))
                    )
                    
                    # Clear the field first
                    title_field.clear()
                    self.random_delay(1, 2)
                    
                    # Click the field to ensure focus
                    title_field.click()
                    self.random_delay(1, 2)
                    
                    # Send keys with a small delay between each character
                    for char in search_query:
                        title_field.send_keys(char)
                        time.sleep(0.1)
                    
                    self.random_delay(1, 2)
                    
                    # Verify job title was entered
                    if title_field.get_attribute('value'):
                        break
                    else:
                        if attempt < max_retries - 1:
                            logger.warning(f"Failed to enter job title on attempt {attempt + 1}, retrying...")
                            continue
                        else:
                            logger.error("Failed to enter job title after all attempts")
                            return None
                            
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error entering job title on attempt {attempt + 1}: {str(e)}")
                        self.random_delay(2, 3)
                        continue
                    else:
                        logger.error(f"Failed to enter job title: {str(e)}")
                        return None

            # Wait for and fill location
            try:
                location_field = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "input[aria-label='City, state, or zip code']"))
                )
                
                # Clear the field first
                location_field.clear()
                self.random_delay(1, 2)
                
                # Click the field to ensure focus
                location_field.click()
                self.random_delay(1, 2)
                
                # Send keys with a small delay between each character
                for char in location:
                    location_field.send_keys(char)
                    time.sleep(0.1)
                
                self.random_delay(1, 2)
                
                # Verify location was entered
                if not location_field.get_attribute('value'):
                    logger.error("Failed to enter location")
                    return None
                    
            except Exception as e:
                logger.error(f"Failed to enter location: {str(e)}")
                return None

            # Try to find and click search button, if not found, press Enter
            try:
                # First try to find the search button by its text
                try:
                    search_button = WebDriverWait(self.driver, 5).until(
                        EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Search')]"))
                    )
                    
                    # Scroll button into view
                    self.driver.execute_script("arguments[0].scrollIntoView(true);", search_button)
                    self.random_delay(1, 2)
                    
                    # Try regular click first
                    try:
                        search_button.click()
                    except:
                        # If regular click fails, try JavaScript click
                        self.driver.execute_script("arguments[0].click();", search_button)
                except:
                    # If button not found or not clickable, press Enter on location field
                    logger.info("Search button not found, pressing Enter on location field")
                    location_field.send_keys(Keys.RETURN)
                
                self.random_delay(3, 5)
                
                # Verify we're on search results page
                if "jobs/search" not in self.driver.current_url:
                    logger.error("Failed to navigate to search results")
                    return None

                # Check for "No matching jobs found" message
                try:
                    no_results_banner = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-search-no-results-banner"))
                    )
                    no_results_text = no_results_banner.find_element(By.CSS_SELECTOR, "p.t-24.t-black.t-normal").text.strip()
                    
                    if "No matching jobs found" in no_results_text:
                        logger.warning(f"No jobs found for search: {job_title} in {location}")
                        print(f"\nNo jobs found for search: {job_title} in {location}")
                        return None
                except TimeoutException:
                    # No "no results" banner found, which means we have results
                    pass
                except Exception as e:
                    logger.error(f"Error checking for no results message: {str(e)}")
                    return None
                
                print(f"Successfully searched for {job_title} in {location}")
                return self.driver.current_url
                
            except Exception as e:
                logger.error(f"Failed to perform search: {str(e)}")
                return None

        except Exception as e:
            logger.error(f"Failed to search jobs: {str(e)}")
            print(f"Failed to search jobs: {str(e)}")
            return None

    def extract_fields_from_description(self, job_description: str) -> Dict:
        """Extract specific fields from job description using OpenAI API."""
        try:
            logger.info("Starting OpenAI API extraction...")
            
            prompt = f"""Analyze the following job description and extract the following information in a structured format:
            1. Industry/Domain: The main industry or domain this job belongs to
            2. Tech Stack/Skills: List of technical skills, programming languages, tools, and technologies required
            3. Benefits: List of benefits and perks offered
            4. Qualifications: List of required academic qualifications
            5. Contract Duration: The duration of the contract if mentioned (e.g., "6 months", "1 year", "Permanent")
            6. Expected Hours Per Week: The expected working hours per week if mentioned
            7. Required Skills: List of specific skills required for the job

            Job Description:
            {job_description}

            Please provide the information in the following format:
            Industry/Domain: [industry/domain]
            Tech Stack/Skills: [comma-separated list of skills]
            Benefits: [comma-separated list of benefits]
            Qualifications: [comma-separated list of qualifications]
            Contract Duration: [duration]
            Expected Hours Per Week: [hours]
            Required Skills: [comma-separated list of skills]

            If any information is not found in the job description, respond with "Not Applicable" for that field.
            Do not make assumptions or provide default values. If the information is not explicitly mentioned, use "Not Applicable".
            For Tech Stack/Skills and Required Skills, make sure to list all technical skills, programming languages, tools, and technologies mentioned in the job description."""

            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a job description analyzer. Extract specific information from job descriptions in a structured format. If information is not found, respond with 'Not Applicable'. Do not make assumptions or provide default values. For skills fields, make sure to list all technical skills, programming languages, tools, and technologies mentioned."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000
            )
            
            # Parse the response
            result = response.choices[0].message.content.strip()
            logger.info(f"OpenAI API response:\n{result}")
            
            # Initialize fields with "Not Applicable"
            fields = {
                'industry': 'Not Applicable',
                'tech_skills': 'Not Applicable',
                'benefits': 'Not Applicable',
                'qualifications': 'Not Applicable',
                'contract_duration': 'Not Applicable',
                'expected_hours_per_week': 'Not Applicable',
                'required_skills': 'Not Applicable'
            }
            
            # Extract fields from the response
            for line in result.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Only update if value is not empty and not "Not Applicable"
                    if value and value.lower() != 'not applicable':
                        if key == 'Industry/Domain':
                            fields['industry'] = value
                            logger.info(f"Found industry: {value}")
                        elif key == 'Tech Stack/Skills':
                            fields['tech_skills'] = value
                            logger.info(f"Found tech skills: {value}")
                        elif key == 'Benefits':
                            fields['benefits'] = value
                            logger.info(f"Found benefits: {value}")
                        elif key == 'Qualifications':
                            fields['qualifications'] = value
                            logger.info(f"Found qualifications: {value}")
                        elif key == 'Contract Duration':
                            fields['contract_duration'] = value
                            logger.info(f"Found contract duration: {value}")
                        elif key == 'Expected Hours Per Week':
                            fields['expected_hours_per_week'] = value
                            logger.info(f"Found expected hours per week: {value}")
                        elif key == 'Required Skills':
                            fields['required_skills'] = value
                            logger.info(f"Found required skills: {value}")
                    else:
                        logger.info(f"No value found for {key}, using 'Not Applicable'")

            logger.info("Final fields extracted:")
            for key, value in fields.items():
                logger.info(f"{key}: {value}")

            return fields

        except Exception as e:
            logger.error(f"Error extracting fields from description: {str(e)}")
            return {
                'industry': 'Not Applicable',
                'tech_skills': 'Not Applicable',
                'benefits': 'Not Applicable',
                'qualifications': 'Not Applicable',
                'contract_duration': 'Not Applicable',
                'expected_hours_per_week': 'Not Applicable',
                'required_skills': 'Not Applicable'
            }

    def extract_job_details(self, job_card, domain: str, software: str) -> Dict:
        """Extract details from a single job card."""
        try:
            job_data = {
                'job_title': 'Not Applicable',
                'company_name': 'Not Applicable',
                'job_location': 'Not Applicable',
                'employment_type': 'Not Applicable',
                'salary_range': 'Not Applicable',
                'work_location_type': 'Not Applicable',
                'posted_date': 'Not Applicable',
                'apply_button_label': 'Not Applicable',
                'apply_url': 'Not Applicable',
                'seniority_level': 'Not Applicable',
                'job_id': 'Not Applicable',
                'industry': 'Not Applicable',
                'comp_desc': 'Not Applicable',
                'tech_skills': 'Not Applicable',
                'benefits': 'Not Applicable',
                'qualifications': 'Not Applicable',
                'full_job_description': 'Not Applicable',
                'c_logo': 'Not Applicable',
                'extract_date': datetime.now().isoformat(),
                'domain_name': domain,
                'software_name': software,
                'contract_duration': 'Not Applicable',
                'expected_hours_per_week': 'Not Applicable',
                'required_skills': 'Not Applicable',
                'llm_converted': 0,
                'seen': True
            }

            # Get the job URL and reference ID
            try:
                job_link = job_card.find_element(By.CSS_SELECTOR, "a.job-card-container__link, a.base-card__full-link")
                job_url = job_link.get_attribute('href')
                # Extract job reference ID from URL's currentJobId parameter
                if 'currentJobId=' in job_url:
                    job_data['job_id'] = job_url.split('currentJobId=')[1].split('&')[0]
                else:
                    # Try to get it from the current page URL if not in the job link
                    current_url = self.driver.current_url
                    if 'currentJobId=' in current_url:
                        job_data['job_id'] = current_url.split('currentJobId=')[1].split('&')[0]
            except:
                pass

            # Click on job card to get more details
            try:
                job_link.click()
                self.random_delay(2, 3)
            except Exception as e:
                logger.error(f"Failed to click job card: {str(e)}")
                return None

            # Wait for job description to load
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-description__content"))
                )
            except TimeoutException:
                logger.error("Timeout waiting for job description to load")
                return None

            # Extract job title
            try:
                job_data['job_title'] = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "h1.t-24.t-bold.inline"
                ).text.strip()
            except NoSuchElementException:
                pass

            # Extract company name
            try:
                job_data['company_name'] = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "div.job-details-jobs-unified-top-card__company-name a"
                ).text.strip()
            except NoSuchElementException:
                pass

            # Extract location
            try:
                location_element = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text.tvm__text--low-emphasis"
                )
                job_data['job_location'] = location_element.text.strip()
            except NoSuchElementException:
                pass

            # Extract work mode, employment type, and seniority level
            try:
                # Find all preference pills
                preference_pills = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "div.job-details-preferences-and-skills__pill span.ui-label"
                )
                
                logger.info(f"Found {len(preference_pills)} preference pills")
                
                for pill in preference_pills:
                    text = pill.text.strip()
                    logger.info(f"Processing preference pill: {text}")
                    
                    # Check for employment type
                    if any(emp_type in text for emp_type in ['Full-time', 'Contract', 'Part-time', 'Temporary']):
                        job_data['employment_type'] = text
                        logger.info(f"Found employment type: {text}")
                    
                    # Check for work mode
                    if any(mode in text for mode in ['Remote', 'Hybrid', 'On-site']):
                        job_data['work_location_type'] = text
                        logger.info(f"Found work mode: {text}")
                    
                    # Check for seniority level with expanded list
                    seniority_keywords = [
                        'Entry level', 'Mid-Senior level', 'Senior level', 'Associate',
                        'Mid level', 'Senior', 'Lead', 'Architect', 'Principal',
                        'Junior', 'Intermediate', 'Expert', 'Director', 'Manager',
                        'Staff', 'Senior Staff', 'Executive'
                    ]
                    
                    if any(keyword.lower() in text.lower() for keyword in seniority_keywords):
                        job_data['seniority_level'] = text
                        logger.info(f"Found seniority level: {text}")
                        
            except Exception as e:
                logger.error(f"Failed to extract work preferences: {str(e)}")
                pass

            # Extract salary range
            try:
                # Find all spans that might contain salary information
                salary_spans = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "span[dir='ltr']"
                )
                
                for span in salary_spans:
                    text = span.text.strip()
                    if '/yr' in text or '/hr' in text:
                        job_data['salary_range'] = text
                        break
                        
            except NoSuchElementException:
                pass

            # Extract posted date
            try:
                date_elements = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    "div.job-details-jobs-unified-top-card__tertiary-description-container span.tvm__text"
                )
                for element in date_elements:
                    text = element.text.strip()
                    if any(x in text.lower() for x in ['hour', 'day', 'month', 'ago']):
                        job_data['posted_date'] = self.calculate_posted_date(text)
                        break
            except NoSuchElementException:
                pass

            # Extract apply button information
            try:
                # First check if apply button exists
                apply_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR, 
                    "button.jobs-apply-button"
                )
                
                if not apply_buttons:
                    # No apply button found
                    job_data['apply_button_label'] = 'Not Applicable'
                    job_data['apply_url'] = 'Not Applicable'
                else:
                    apply_button = apply_buttons[0]
                    job_data['apply_button_label'] = apply_button.text.strip()
                    
                    # Only proceed with URL extraction if it's not an Easy Apply button
                    if job_data['apply_button_label'] != "Easy Apply":
                        try:
                            # Store the current window handle
                            main_window = self.driver.current_window_handle
                            
                            # Click the apply button
                            apply_button.click()
                            self.random_delay(2, 3)
                            
                            # Wait for new tab to open and switch to it
                            WebDriverWait(self.driver, 10).until(
                                lambda d: len(d.window_handles) > 1
                            )
                            
                            # Switch to the new tab
                            new_window = [handle for handle in self.driver.window_handles if handle != main_window][0]
                            self.driver.switch_to.window(new_window)
                            
                            # Get the URL from the new tab
                            job_data['apply_url'] = self.driver.current_url
                            
                            # Close the new tab
                            self.driver.close()
                            
                            # Switch back to the main window
                            self.driver.switch_to.window(main_window)
                            
                        except Exception as e:
                            logger.error(f"Failed to get Apply URL: {str(e)}")
                            job_data['apply_url'] = 'Not Applicable'
                    else:
                        job_data['apply_url'] = 'Not Applicable'
                    
            except Exception as e:
                logger.error(f"Error processing apply button: {str(e)}")
                job_data['apply_button_label'] = 'Not Applicable'
                job_data['apply_url'] = 'Not Applicable'

            # Extract and save company logo
            try:
                logo_element = self.driver.find_element(
                    By.CSS_SELECTOR, 
                    "img.ivm-view-attr__img--centered"
                )
                logo_url = logo_element.get_attribute('src')
                if logo_url:
                    # Create logos directory if it doesn't exist
                    os.makedirs('logos', exist_ok=True)
                    
                    # Generate filename using company name and job reference ID
                    company_name = job_data['company_name'].replace(' ', '_').lower()
                    job_id = job_data['job_id']
                    logo_filename = f"logos/{company_name}_{job_id}.png"
                    
                    # Download and save the image
                    response = requests.get(logo_url)
                    if response.status_code == 200:
                        with open(logo_filename, 'wb') as f:
                            f.write(response.content)
                        job_data['c_logo'] = logo_filename
                    else:
                        job_data['c_logo'] = 'Not Applicable'
            except Exception as e:
                logger.error(f"Failed to save company logo: {str(e)}")
                job_data['c_logo'] = 'Not Applicable'

            # Extract company description
            try:
                logger.info("Starting company description extraction...")
                
                # Try multiple selectors for company description
                company_desc_selectors = [
                    "p.jobs-company__company-description div.DSkFjPIRUfGDmNnMiGtRQTFCGOMZBo",  # Primary selector
                    "div.DSkFjPIRUfGDmNnMiGtRQTFCGOMZBo",  # Direct div selector
                    "p.jobs-company__company-description",  # Parent paragraph
                    "div.jobs-company__company-description",  # Alternative container
                    "div.jobs-company__description"  # Another alternative
                ]
                
                company_desc = None
                for selector in company_desc_selectors:
                    try:
                        logger.info(f"Trying company description selector: {selector}")
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        logger.info(f"Found {len(elements)} elements with selector: {selector}")
                        
                        for element in elements:
                            if element.is_displayed() and element.text.strip():
                                company_desc = element
                                logger.info(f"Found visible company description with selector: {selector}")
                                logger.info(f"Element text length: {len(element.text.strip())}")
                                logger.info(f"Complete element text:\n{element.text.strip()}")
                                break
                        if company_desc:
                            break
                    except Exception as e:
                        logger.warning(f"Failed with selector {selector}: {str(e)}")
                        continue

                if company_desc:
                    # Get the complete text
                    full_text = company_desc.text.strip()
                    logger.info(f"Raw company description text length: {len(full_text)}")
                    logger.info(f"Complete raw company description text:\n{full_text}")
                    
                    # Remove the "show more" button text if present
                    if '…' in full_text:
                        full_text = full_text.split('…')[0].strip()
                        logger.info("Removed 'show more' button text")
                    
                    # Clean up any extra whitespace and line breaks
                    full_text = ' '.join(full_text.split())
                    logger.info("Cleaned up whitespace and line breaks")
                    
                    # Remove any suspicious URLs
                    full_text = full_text.replace('https://www.linkedin.com/redir/suspicious-page?url=', '')
                    logger.info("Removed suspicious URLs")
                    
                    # Clean up any remaining HTML-like tags
                    full_text = full_text.replace('<br>', ' ').replace('<br><br>', '\n')
                    logger.info("Cleaned up HTML tags")
                    
                    # Remove any extra spaces around newlines
                    full_text = '\n'.join(line.strip() for line in full_text.split('\n'))
                    logger.info("Cleaned up newlines")
                    
                    # Verify we have actual content
                    if len(full_text.strip()) > 0:
                        job_data['comp_desc'] = full_text
                        logger.info(f"Successfully extracted company description. Final length: {len(full_text)}")
                        logger.info(f"Final company description text:\n{full_text}")
                    else:
                        logger.warning("Company description text is empty after cleaning")
                        job_data['comp_desc'] = 'Not Applicable'
                else:
                    logger.warning("Company description element not found with any selector")
                    job_data['comp_desc'] = 'Not Applicable'
                    
            except Exception as e:
                logger.error(f"Failed to extract company description: {str(e)}")
                job_data['comp_desc'] = 'Not Applicable'

            # Extract benefits
            try:
                benefits_section = self.driver.find_element(
                    By.XPATH,
                    "//strong[contains(text(), 'Benefits')]/following-sibling::ul"
                )
                job_data['benefits'] = benefits_section.text.strip()
            except NoSuchElementException:
                pass

            # Extract qualifications
            try:
                qualifications_section = self.driver.find_element(
                    By.XPATH,
                    "//strong[contains(text(), 'Qualifications')]/following-sibling::ul"
                )
                job_data['qualifications'] = qualifications_section.text.strip()
            except NoSuchElementException:
                pass

            # Extract full job description
            try:
                job_desc = self.driver.find_element(
                    By.CSS_SELECTOR,
                    "div.jobs-description__content div.jobs-box__html-content"
                )
                job_data['full_job_description'] = job_desc.text.strip()
                
                # Extract additional fields using OpenAI
                extracted_fields = self.extract_fields_from_description(job_data['full_job_description'])
                
                # Map the extracted fields to job_data
                job_data.update({
                    'industry': extracted_fields.get('industry', 'Not Applicable'),
                    'tech_skills': extracted_fields.get('tech_skills', 'Not Applicable'),
                    'benefits': extracted_fields.get('benefits', 'Not Applicable'),
                    'qualifications': extracted_fields.get('qualifications', 'Not Applicable'),
                    'contract_duration': extracted_fields.get('contract_duration', 'Not Applicable'),
                    'expected_hours_per_week': extracted_fields.get('expected_hours_per_week', 'Not Applicable'),
                    'required_skills': extracted_fields.get('required_skills', 'Not Applicable')
                })
                
            except NoSuchElementException:
                pass

            # Print job details to terminal
            self.print_job_details(job_data)

            return job_data

        except Exception as e:
            logger.error(f"Failed to extract job details: {str(e)}")
            print(f"Failed to extract job details: {str(e)}")
            return None

    def rotate_proxy(self):
        """Rotate to the next proxy with natural delays."""
        try:
            # Get next proxy
            proxy = self.get_next_proxy()
            
            # Add natural delay before rotation
            self.random_delay(5, 10)
            
            # Create new proxy extension
            manifest_json = """
            {
                "version": "1.0.0",
                "manifest_version": 2,
                "name": "Chrome Proxy",
                "permissions": [
                    "proxy",
                    "tabs",
                    "unlimitedStorage",
                    "storage",
                    "webRequest",
                    "webRequestBlocking"
                ],
                "background": {
                    "scripts": ["background.js"]
                }
            }
            """

            background_js = """
            var config = {
                mode: "fixed_servers",
                rules: {
                    singleProxy: {
                        scheme: "http",
                        host: "%s",
                        port: %s
                    },
                    bypassList: []
                }
            };

            chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

            function callbackFn(details) {
                return {
                    authCredentials: {
                        username: "%s",
                        password: "%s"
                    }
                };
            }

            chrome.webRequest.onAuthRequired.addListener(
                callbackFn,
                {urls: ["<all_urls>"]},
                ['blocking']
            );
            """ % (
                proxy.split(':')[0],
                proxy.split(':')[1],
                self.proxy_username,
                self.proxy_password
            )

            # Create proxy extension directory
            import os
            import zipfile
            import tempfile

            plugin_dir = os.path.join(tempfile.gettempdir(), 'proxy_auth_plugin')
            if not os.path.exists(plugin_dir):
                os.mkdir(plugin_dir)

            with open(os.path.join(plugin_dir, "manifest.json"), "w") as f:
                f.write(manifest_json)
            with open(os.path.join(plugin_dir, "background.js"), "w") as f:
                f.write(background_js)

            # Create proxy extension
            plugin_path = os.path.join(plugin_dir, "proxy_auth_plugin.zip")
            with zipfile.ZipFile(plugin_path, 'w') as zp:
                zp.write(os.path.join(plugin_dir, "manifest.json"), "manifest.json")
                zp.write(os.path.join(plugin_dir, "background.js"), "background.js")

            # Clear browser data
            self.driver.execute_script("window.localStorage.clear();")
            self.driver.execute_script("window.sessionStorage.clear();")
            self.driver.delete_all_cookies()
            
            # Add natural delay after clearing data
            self.random_delay(3, 5)
            
            # Refresh the page
            current_url = self.driver.current_url
            self.driver.get(current_url)
            
            # Add longer delay after rotation
            self.random_delay(8, 15)
            
            logger.info(f"Successfully rotated to proxy: {proxy}")
            return True
        except Exception as e:
            logger.error(f"Failed to rotate proxy: {str(e)}")
            return False

    def handle_error(self, error_type: str, max_retries: int = 2) -> bool:
        """Handle errors gracefully with natural delays."""
        try:
            if error_type == "navigation":
                # Simple page refresh with delay
                self.driver.refresh()
                self.random_delay(3, 5)
            elif error_type == "element":
                # Wait and retry with delay
                self.random_delay(2, 4)
            elif error_type == "session":
                # Check if we're on login page
                if "login" in self.driver.current_url.lower():
                    logger.info("Session lost, attempting to login")
                    return self.login()
            elif error_type == "rate_limit":
                # Longer delay for rate limits
                self.random_delay(60, 120)  # 1-2 minutes
            return True
        except Exception as e:
            logger.error(f"Error handling failed: {str(e)}")
            return False

    def validate_job_data(self, job_data: Dict) -> bool:
        """Validate essential job data fields."""
        try:
            # Only check essential fields
            essential_fields = [
                'job_title',
                'company_name',
                'job_id',
                'full_job_description'
            ]
            
            # Check if all essential fields are present and not empty
            for field in essential_fields:
                if not job_data.get(field) or job_data.get(field) == 'Not Applicable':
                    logger.warning(f"Missing essential field: {field}")
                    return False
                    
            return True
        except Exception as e:
            logger.error(f"Data validation error: {str(e)}")
            return False

    def process_search_results(self, search_url: str, output_file: str, domain: str, software: str, search_id: str, job_limit: Optional[int] = None) -> List[Dict]:
        """Process all job listings from search results."""
        jobs_data = []
        max_retries = 2  # Reduced retries
        jobs_per_page = 25
        page = 1
        jobs_processed = 0
        total_jobs_processed = 0
        current_url = search_url

        while True:
            try:
                # Check if we've reached the job limit
                if job_limit is not None and total_jobs_processed >= job_limit:
                    logger.info(f"Reached job limit of {job_limit} jobs")
                    break

                # Check if it's time to rotate proxy (every 200 jobs)
                if total_jobs_processed > 0 and total_jobs_processed % 200 == 0:
                    logger.info(f"Rotating proxy after processing {total_jobs_processed} jobs")
                    if not self.rotate_proxy():
                        logger.error("Failed to rotate proxy, continuing with current proxy")
                    self.random_delay(10, 15)  # Longer delay after proxy rotation

                # Calculate start parameter for pagination
                start_param = (page - 1) * jobs_per_page
                
                # Construct the URL for the current page
                if page == 1:
                    current_url = search_url
                else:
                    # Add or update the start parameter in the URL
                    if 'start=' in search_url:
                        current_url = search_url.split('start=')[0] + f'start={start_param}'
                    else:
                        current_url = f"{search_url}&start={start_param}"

                # Navigate to the page if not already there
                if self.driver.current_url != current_url:
                    try:
                        logger.info(f"Navigating to page {page} with URL: {current_url}")
                        self.driver.get(current_url)
                        self.random_delay(3, 5)
                    except Exception as e:
                        logger.error(f"Failed to navigate to page {page}: {str(e)}")
                        if not self.handle_error("navigation"):
                            return jobs_data

                # Wait for job cards to load with multiple possible selectors
                job_cards = []
                selectors = [
                    "li.ember-view.aUvdHPFertpnIJPPQuqaOLBKDiHTTANo.occludable-update.p0.relative.scaffold-layout__list-item",
                    "li.ember-view.occludable-update.p0.relative.scaffold-layout__list-item",
                    "li.ember-view.job-card-container",
                    "div.job-card-container",
                    "div.base-card"
                ]
                
                for selector in selectors:
                    try:
                        logger.info(f"Trying to find job cards with selector: {selector}")
                        job_cards = WebDriverWait(self.driver, 15).until(
                            EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                        )
                        if job_cards:
                            logger.info(f"Found {len(job_cards)} job cards with selector: {selector}")
                            break
                    except TimeoutException:
                        logger.warning(f"Timeout with selector: {selector}")
                        continue
                    except Exception as e:
                        logger.warning(f"Error with selector {selector}: {str(e)}")
                        continue

                if not job_cards:
                    logger.error("No job cards found with any selector")
                    # Try to refresh the page once
                    try:
                        logger.info("Attempting to refresh the page...")
                        self.driver.refresh()
                        self.random_delay(5, 7)
                        # Try the first selector again after refresh
                        job_cards = WebDriverWait(self.driver, 15).until(
                            EC.presence_of_all_elements_located((By.CSS_SELECTOR, selectors[0]))
                        )
                        if not job_cards:
                            logger.error("Still no job cards found after refresh")
                            return jobs_data
                    except Exception as e:
                        logger.error(f"Failed to refresh page: {str(e)}")
                        return jobs_data

                print(f"\nProcessing page {page}...")
                
                # Natural scroll through the page
                self.natural_scroll()
                
                # Process each job card
                for index, job_card in enumerate(job_cards):
                    # Check if we've reached the job limit
                    if job_limit is not None and total_jobs_processed >= job_limit:
                        logger.info(f"Reached job limit of {job_limit} jobs")
                        return jobs_data

                    retry_count = 0
                    while retry_count < max_retries:
                        try:
                            # Natural scroll to the job card
                            self.natural_scroll(job_card)
                            self.random_delay(1, 2)

                            # Get job title before clicking (for logging)
                            try:
                                job_title = job_card.find_element(By.CSS_SELECTOR, "h3.base-search-card__title").text.strip()
                            except:
                                try:
                                    job_title = job_card.find_element(By.CSS_SELECTOR, "a.job-card-container__link strong").text.strip()
                                except:
                                    job_title = f"Job {index + 1}"

                            print(f"\nProcessing job: {job_title}")

                            # Click the job card
                            try:
                                # Try multiple selectors for the clickable element
                                clickable_selectors = [
                                    "a.base-card__full-link",
                                    "a.job-card-container__link",
                                    "div.job-card-container__primary-description"
                                ]
                                
                                clickable_element = None
                                for selector in clickable_selectors:
                                    try:
                                        clickable_element = job_card.find_element(By.CSS_SELECTOR, selector)
                                        if clickable_element:
                                            break
                                    except:
                                        continue
                                
                                if not clickable_element:
                                    logger.error(f"Could not find clickable element for job: {job_title}")
                                    break

                                # Natural scroll to the element
                                self.natural_scroll(clickable_element)
                                self.random_delay(1, 2)
                                
                                # Try multiple click methods
                                try:
                                    clickable_element.click()
                                except:
                                    try:
                                        self.driver.execute_script("arguments[0].click();", clickable_element)
                                    except:
                                        # Try moving to element and clicking
                                        actions = webdriver.ActionChains(self.driver)
                                        actions.move_to_element(clickable_element).click().perform()
                                
                                self.random_delay(2, 3)
                                
                                # Verify the job description loaded
                                try:
                                    WebDriverWait(self.driver, 10).until(
                                        EC.presence_of_element_located((By.CSS_SELECTOR, "div.jobs-description__content"))
                                    )
                                except TimeoutException:
                                    logger.error(f"Job description did not load for: {job_title}")
                                    break
                                    
                            except Exception as e:
                                logger.error(f"Failed to click job card: {str(e)}")
                                break

                            # Extract job details
                            job_data = self.extract_job_details(job_card, domain, software)
                            
                            # Validate job data
                            if job_data and self.validate_job_data(job_data):
                                # Add search_id to job data
                                job_data['search_id'] = search_id
                                # Save to MongoDB
                                try:
                                    self.save_job_to_mongodb(job_data)
                                    jobs_data.append(job_data)
                                    jobs_processed += 1
                                    total_jobs_processed += 1
                                    print(f"Successfully extracted and saved details for: {job_data['job_title']}")
                                except Exception as e:
                                    logger.error(f"Failed to save job to MongoDB: {str(e)}")
                                break  # Success, exit retry loop
                            else:
                                logger.warning(f"Invalid job data for job {index + 1}")
                                break

                        except Exception as e:
                            logger.error(f"Failed to process job card: {str(e)}")
                            retry_count += 1
                            if retry_count < max_retries:
                                logger.info(f"Retrying job card (attempt {retry_count + 1}/{max_retries})")
                                self.random_delay(2, 4)
                            else:
                                logger.error(f"Max retries reached for job card")
                                break

                # Add natural delay between pages
                self.random_delay(5, 10)
                
                # Increment page number for next iteration
                page += 1

            except Exception as e:
                logger.error(f"Failed to process page {page}: {str(e)}")
                if not self.handle_error("navigation"):
                    break

        return jobs_data

    def set_existing_jobs_unseen(self, search_id: str):
        """Set all existing jobs for a search criteria to unseen without changing active status."""
        try:
            update_result = self.collection.update_many(
                {"search_id": search_id},
                {"$set": {"seen": False}}
            )
            logger.info(f"Set {update_result.modified_count} existing jobs to unseen for search_id: {search_id}")
            return update_result.modified_count
        except Exception as e:
            logger.error(f"Error setting jobs to unseen: {str(e)}")
            return 0

    def set_unseen_jobs_inactive(self, search_id: str):
        """Set active to false for all jobs that were not seen in the current scrape."""
        try:
            update_result = self.collection.update_many(
                {
                    "search_id": search_id,
                    "seen": False
                },
                {"$set": {"active": False}}
            )
            logger.info(f"Set {update_result.modified_count} unseen jobs to inactive for search_id: {search_id}")
            return update_result.modified_count
        except Exception as e:
            logger.error(f"Error setting unseen jobs to inactive: {str(e)}")
            return 0

    def save_job_to_mongodb(self, job_data: Dict):
        """Save or update job in MongoDB."""
        try:
            logger.info(f"Attempting to save job {job_data.get('job_id', 'unknown')} to MongoDB")
            
            # Verify MongoDB connection before saving
            if not self.check_mongodb_connection():
                logger.error("MongoDB connection lost, attempting to reconnect...")
                self.mongo_client = MongoClient('mongodb://localhost:27017/')
                self.db = self.mongo_client['linkedin_jobs']
                self.collection = self.db['jobdetails']
                if not self.check_mongodb_connection():
                    raise Exception("Failed to reconnect to MongoDB")
                logger.info("Successfully reconnected to MongoDB")

            # Ensure job_id is not None
            if not job_data.get('job_id'):
                logger.error("Cannot save job with null job_id")
                return

            # Ensure search_id is present
            if not job_data.get('search_id'):
                logger.error("Cannot save job without search_id")
                return

            # Log the job data being saved
            logger.info(f"Job data to save: {json.dumps(job_data, indent=2)}")

            # Check if job already exists
            existing_job = self.collection.find_one(
                {"job_id": job_data['job_id']}
            )

            if existing_job:
                logger.info(f"Job {job_data['job_id']} already exists in database")
                
                # Update existing job and set seen and active to true
                update_result = self.collection.update_one(
                    {"job_id": job_data['job_id']},
                    {
                        "$set": {
                            "seen": True,
                            "active": True,
                            "search_id": job_data['search_id'],
                            "job_title": job_data['job_title'],
                            "job_location": job_data['job_location'],
                            "company_name": job_data['company_name'],
                            "employment_type": job_data['employment_type'],
                            "salary_range": job_data['salary_range'],
                            "work_location_type": job_data['work_location_type'],
                            "posted_date": job_data['posted_date'],
                            "apply_button_label": job_data['apply_button_label'],
                            "apply_url": job_data['apply_url'],
                            "seniority_level": job_data['seniority_level'],
                            "industry": job_data['industry'],
                            "comp_desc": job_data['comp_desc'],
                            "tech_skills": job_data['tech_skills'],
                            "benefits": job_data['benefits'],
                            "qualifications": job_data['qualifications'],
                            "full_job_description": job_data['full_job_description'],
                            "c_logo": job_data['c_logo'],
                            "extract_date": job_data['extract_date'],
                            "domain_name": job_data['domain_name'],
                            "software_name": job_data['software_name'],
                            "contract_duration": job_data['contract_duration'],
                            "expected_hours_per_week": job_data['expected_hours_per_week'],
                            "required_skills": job_data['required_skills'],
                            "llm_converted": job_data['llm_converted']
                        }
                    }
                )
                logger.info(f"Update result: {update_result.modified_count} documents modified")
                logger.info(f"Updated existing job {job_data['job_id']}")
            else:
                logger.info(f"Job {job_data['job_id']} is new, inserting into database")
                # For new jobs, set seen and active to true
                job_data['seen'] = True
                job_data['active'] = True
                
                # Insert the job data
                insert_result = self.collection.insert_one(job_data)
                logger.info(f"Insert result: {insert_result.inserted_id}")
                logger.info(f"Added new job {job_data['job_id']}")

            # Verify the save operation
            saved_job = self.collection.find_one({"job_id": job_data['job_id']})
            if saved_job:
                logger.info(f"Successfully verified job {job_data['job_id']} in database")
            else:
                logger.error(f"Failed to verify job {job_data['job_id']} in database")

        except Exception as e:
            logger.error(f"Error saving job to MongoDB: {str(e)}")
            logger.error(f"Job data that failed to save: {json.dumps(job_data, indent=2)}")
            raise  # Re-raise the exception to handle it in the calling code

    def save_to_csv(self, jobs: List[Dict], filename: str = "linkedin_jobs.csv"):
        """Save job data to CSV file."""
        try:
            if not jobs:
                logger.warning("No jobs to save")
                return

            # Define CSV headers
            headers = [
                'job_id', 'title', 'company', 'location', 'job_type', 'posted_date',
                'applicants', 'salary', 'full_job_description', 'industry', 'tech_skills',
                'benefits', 'qualifications', 'contract_duration', 'expected_hours_per_week',
                'required_skills', 'scraped_date', 'llm_converted'
            ]

            # Create DataFrame
            df = pd.DataFrame(jobs)
            
            # Ensure all columns exist
            for header in headers:
                if header not in df.columns:
                    df[header] = 'Not Applicable'

            # Reorder columns
            df = df[headers]

            # Save to CSV
            df.to_csv(filename, index=False)
            logger.info(f"Saved {len(jobs)} jobs to {filename}")

        except Exception as e:
            logger.error(f"Error saving to CSV: {str(e)}")
            raise

    def get_or_create_search_criteria(self, job_title: str, location: str, domain: str, software: str) -> str:
        """Get existing search criteria or create new one and return search_id."""
        try:
            # Try to find existing search criteria
            search_criteria = self.search_criteria_collection.find_one({
                "job_title": job_title,
                "location": location,
                "software": software
            })
            
            if search_criteria:
                logger.info(f"Found existing search criteria with ID: {search_criteria['_id']}")
                # Increment iteration count
                self.search_criteria_collection.update_one(
                    {"_id": search_criteria['_id']},
                    {"$inc": {"iteration": 1}}
                )
                return str(search_criteria['_id'])
            
            # Create new search criteria if not found
            new_search = {
                "job_title": job_title,
                "location": location,
                "domain": domain,
                "software": software,
                "created_at": datetime.now().isoformat(),
                "iteration": 1  # Start with iteration 1
            }
            
            result = self.search_criteria_collection.insert_one(new_search)
            logger.info(f"Created new search criteria with ID: {result.inserted_id}")
            return str(result.inserted_id)
            
        except Exception as e:
            logger.error(f"Error in get_or_create_search_criteria: {str(e)}")
            raise

    def scrape_jobs(self, input_file: str, output_file: str):
        """Main method to scrape jobs based on input CSV."""
        try:
            # Read input CSV
            input_df = pd.read_csv(input_file)
            
            # Initialize output DataFrame
            all_jobs_data = []

            # Login to LinkedIn
            if not self.login():
                raise Exception("Failed to login to LinkedIn")

            # Process each job title and location combination
            for _, row in input_df.iterrows():
                job_title = row['Role']
                location = row['Location']
                domain = row['Domain']
                software = row['Software']
                
                # Get job limit from CSV (if specified)
                job_limit = None
                if 'Limit' in row and pd.notna(row['Limit']):
                    try:
                        job_limit = int(row['Limit'])
                        logger.info(f"Job limit set to {job_limit} for {job_title} in {location}")
                    except ValueError:
                        logger.warning(f"Invalid job limit value for {job_title} in {location}, will scrape all jobs")

                # Get or create search criteria and get search_id
                search_id = self.get_or_create_search_criteria(job_title, location, domain, software)
                
                # Check if this is first iteration (no existing jobs)
                existing_jobs_count = self.collection.count_documents({"search_id": search_id})
                
                if existing_jobs_count > 0:
                    # Subsequent iteration: Set all jobs to unseen
                    self.set_existing_jobs_unseen(search_id)

                logger.info(f"Searching for: {software} {job_title} in {location}")
                print(f"\nSearching for: {software} {job_title} in {location}")
                
                search_url = self.search_jobs(job_title, location, software)
                if search_url:
                    try:
                        jobs_data = self.process_search_results(search_url, output_file, domain, software, search_id, job_limit)
                        if jobs_data:
                            all_jobs_data.extend(jobs_data)
                            
                            # After scraping, set active to false for any jobs that weren't seen
                            if existing_jobs_count > 0:
                                self.set_unseen_jobs_inactive(search_id)
                    except Exception as e:
                        logger.error(f"Error processing search results: {str(e)}")

            if all_jobs_data:
                logger.info(f"Successfully scraped {len(all_jobs_data)} jobs")
                print(f"\nSuccessfully scraped {len(all_jobs_data)} jobs")
            else:
                logger.warning("No jobs were scraped successfully")

        except Exception as e:
            logger.error(f"An error occurred during scraping: {str(e)}")
            print(f"An error occurred during scraping: {str(e)}")
        finally:
            try:
                if self.driver:
                    self.driver.quit()
            except:
                pass

    def __del__(self):
        """Cleanup when the scraper is destroyed."""
        try:
            if self.driver:
                self.driver.quit()
            if self.mongo_client:
                self.mongo_client.close()
        except:
            pass

if __name__ == "__main__":
    # Create .env file if it doesn't exist
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("LINKEDIN_EMAIL=your_email@example.com\n")
            f.write("LINKEDIN_PASSWORD=your_password\n")
        logger.info("Created .env file. Please update with your LinkedIn credentials.")
        print("Created .env file. Please update with your LinkedIn credentials.")

    # Initialize and run scraper
    scraper = LinkedInScraper()
    scraper.scrape_jobs('Input-csv-input-v01.csv', 'linkedin_jobs_output.csv') 