# LinkedIn Job Scraper

A robust LinkedIn job scraper that uses Selenium and MongoDB to collect and store job listings with advanced features like proxy rotation, natural scrolling, and intelligent data extraction.

## Features

- **Intelligent Search**: Combines software and role parameters for precise job searches
- **Proxy Rotation**: Automatic proxy rotation using ProxyMesh to avoid rate limiting
- **Natural Behavior**: Implements human-like scrolling and delays to avoid detection
- **MongoDB Integration**: Stores job data with search criteria tracking
- **Advanced Data Extraction**: Uses OpenAI API to extract structured information from job descriptions
- **Error Handling**: Robust error handling with automatic retries
- **Session Management**: Intelligent session management with natural breaks
- **Company Logo Download**: Automatically downloads and stores company logos
- **Search Criteria Tracking**: Tracks unique combinations of job title, location, and software

## Prerequisites

- Python 3.8+
- MongoDB
- Chrome Browser
- ChromeDriver
- ProxyMesh account (for proxy rotation)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd linkedin-scraper
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your credentials:
```
LINKEDIN_EMAIL=your_email@example.com
LINKEDIN_PASSWORD=your_password
```

4. Ensure MongoDB is running locally on port 27017

## Input CSV Format

Create an input CSV file (e.g., `Input-csv-input-v01.csv`) with the following columns:
- `Role`: Job title to search for
- `Location`: Location to search in
- `Domain`: Domain/industry of the job
- `Software`: Software/technology to include in search
- `Limit` (optional): Maximum number of jobs to scrape

Example:
```csv
Role,Location,Domain,Software,Limit
Software Engineer,New York,Technology,Python,100
Data Scientist,San Francisco,Data Science,R,50
```

## Usage

Run the scraper:
```bash
python linkedin_scraper.py
```

The scraper will:
1. Read the input CSV file
2. Login to LinkedIn
3. For each row in the CSV:
   - Search for jobs using the combined software and role parameters
   - Extract job details including:
     - Basic information (title, company, location)
     - Employment details (type, salary, work mode)
     - Company information (description, logo)
     - Job requirements and benefits
     - Technical skills and qualifications
4. Store the data in MongoDB
5. Download company logos to the `logos` directory

## Data Storage

### MongoDB Collections

1. `jobdetails`: Stores all job listings with fields:
   - Basic job information
   - Company details
   - Technical requirements
   - Benefits and qualifications
   - Search metadata
   - Active status tracking

2. `search_criteria`: Tracks search parameters and iterations:
   - Job title
   - Location
   - Software
   - Domain
   - Iteration count
   - Creation timestamp

### Search Criteria Mechanism

The scraper tracks unique combinations of:
- Job title
- Location
- Software

This allows for:
- Tracking iterations of the same search
- Maintaining separate counts for different software combinations
- Identifying new vs. existing jobs
- Managing active/inactive job status

## Error Handling

The scraper includes robust error handling for:
- Network issues
- Rate limiting
- Session timeouts
- Element not found errors
- Proxy rotation failures

## Logging

Logs are stored in `scraper.log` with detailed information about:
- Search operations
- Data extraction
- Error handling
- Proxy rotation
- MongoDB operations

## Output

1. **MongoDB**: All job data is stored in MongoDB collections
2. **Logos**: Company logos are saved in the `logos` directory
3. **CSV**: Optional CSV export of job data
4. **Logs**: Detailed operation logs in `scraper.log`

## Notes

- The scraper implements natural delays and human-like behavior to avoid detection
- Proxy rotation occurs every 200 jobs to maintain stable connections
- Company logos are downloaded and stored locally
- Search criteria tracking helps manage job status and iterations
- The scraper can handle multiple search combinations simultaneously

## Limitations

- Requires manual intervention for CAPTCHA/OTP verification
- Dependent on LinkedIn's page structure
- Requires active ProxyMesh subscription
- Limited by LinkedIn's rate limiting policies

## Contributing

Feel free to submit issues and enhancement requests!

## Contact

If you have any custom requirements or need assistance, feel free to get in touch at rohit.paul@excelloite.com
