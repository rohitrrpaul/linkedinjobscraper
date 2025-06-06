# Delay configurations for LinkedIn Scraper
# All times are in seconds

# General delays for basic operations
GENERAL_DELAYS = {
    'min_base_delay': 1,      # Minimum base delay for any operation
    'max_base_delay': 3,      # Maximum base delay for any operation
    'multiplier_min': 1.2,    # Minimum multiplier for occasional longer delays
    'multiplier_max': 2.0,    # Maximum multiplier for occasional longer delays
    'additional_delay_min': 0.3,  # Minimum additional random delay
    'additional_delay_max': 0.8,  # Maximum additional random delay
    'long_additional_delay_min': 3,   # Minimum long additional delay
    'long_additional_delay_max': 6    # Maximum long additional delay
}

# Delays specific to login process
LOGIN_DELAYS = {
    'initial_delay_min': 2,   # Minimum delay before starting login process
    'initial_delay_max': 3,   # Maximum delay before starting login process
    'input_delay_min': 0.5,   # Minimum delay between input fields
    'input_delay_max': 1,     # Maximum delay between input fields
    'button_click_delay_min': 0.5,  # Minimum delay before clicking buttons
    'button_click_delay_max': 1.5,  # Maximum delay before clicking buttons
    'post_login_delay_min': 3,    # Minimum delay after successful login
    'post_login_delay_max': 5,    # Maximum delay after successful login
    'login_check_interval': 2,    # Interval between login verification attempts
    'captcha_wait': 60,           # Time to wait for manual captcha completion
    'otp_wait': 30               # Time to wait for manual OTP entry
}

# Delays for job search operations
SEARCH_DELAYS = {
    'pre_search_delay_min': 1,    # Minimum delay before starting search
    'pre_search_delay_max': 2,    # Maximum delay before starting search
    'input_typing_delay': 0.05,   # Delay between typing each character
    'post_input_delay_min': 0.5,   # Minimum delay after entering search terms
    'post_input_delay_max': 1,    # Maximum delay after entering search terms
    'button_click_delay_min': 0.5,  # Minimum delay before clicking search button
    'button_click_delay_max': 1.5   # Maximum delay before clicking search button
}

# Delays for scrolling operations
SCROLL_DELAYS = {
    'scroll_pause_min': 0.3,      # Minimum pause between scrolls
    'scroll_pause_max': 1,        # Maximum pause between scrolls
    'long_scroll_pause_min': 1,   # Minimum pause for occasional longer stops
    'long_scroll_pause_max': 2,   # Maximum pause for occasional longer stops
    'scroll_amount_min': 400,     # Minimum pixels to scroll
    'scroll_amount_max': 800      # Maximum pixels to scroll
}

# Delays for proxy operations
PROXY_DELAYS = {
    'pre_rotation_delay_min': 3,  # Minimum delay before rotating proxy
    'pre_rotation_delay_max': 5,  # Maximum delay before rotating proxy
    'post_rotation_delay_min': 4, # Minimum delay after rotating proxy
    'post_rotation_delay_max': 8   # Maximum delay after rotating proxy
}

# Delays for error handling
ERROR_DELAYS = {
    'retry_delay_min': 1,         # Minimum delay before retrying after error
    'retry_delay_max': 3,         # Maximum delay before retrying after error
    'rate_limit_delay_min': 30,   # Minimum delay for rate limit errors
    'rate_limit_delay_max': 60    # Maximum delay for rate limit errors
}

# Delays for job processing
JOB_PROCESSING_DELAYS = {
    'pre_click_delay_min': 0.5,   # Minimum delay before clicking job card
    'pre_click_delay_max': 1,     # Maximum delay before clicking job card
    'post_click_delay_min': 1,    # Minimum delay after clicking job card
    'post_click_delay_max': 2,    # Maximum delay after clicking job card
    'description_load_delay': 2,   # Delay to wait for job description to load
    'between_jobs_delay_min': 1,   # Minimum delay between processing jobs
    'between_jobs_delay_max': 2    # Maximum delay between processing jobs
}

# Delays for session management
SESSION_DELAYS = {
    'session_duration_min': 20,   # Minimum session duration in minutes
    'session_duration_max': 40,   # Maximum session duration in minutes
    'pause_duration_min': 3,      # Minimum pause duration between sessions
    'pause_duration_max': 8,      # Maximum pause duration between sessions
    'jobs_per_session_min': 30,   # Minimum jobs to process per session
    'jobs_per_session_max': 50    # Maximum jobs to process per session
}

# Mouse movement delays
MOUSE_DELAYS = {
    'movement_delay_min': 0.05,   # Minimum delay between mouse movements
    'movement_delay_max': 0.15,   # Maximum delay between mouse movements
    'movements_per_action_min': 2, # Minimum number of mouse movements
    'movements_per_action_max': 3   # Maximum number of mouse movements
}

# Page load timeouts
TIMEOUTS = {
    'page_load': 20,             # Timeout for page load in seconds
    'element_wait': 8,           # Timeout for element presence in seconds
    'verification_wait': 300,    # Timeout for login verification in seconds
    'search_wait': 10,           # Timeout for search results in seconds
    'description_wait': 8        # Timeout for job description load in seconds
}

# Retry configurations
RETRY_CONFIG = {
    'max_login_attempts': 3,     # Maximum number of login attempts
    'max_search_attempts': 3,    # Maximum number of search attempts
    'max_job_attempts': 2,       # Maximum number of job processing attempts
    'max_proxy_attempts': 3      # Maximum number of proxy rotation attempts
} 