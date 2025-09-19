#!/usr/bin/env python3
"""
Python script to query the combined-schedule table from DoltHub using LLM-generated SQL.
Repository: https://www.dolthub.com/repositories/gmichnikov/sports-schedules
"""

import requests
import json
import sys
import argparse
from anthropic import Anthropic
from dotenv import load_dotenv
import os
from datetime import datetime
import pytz

def get_current_eastern_date():
    """Get current date in Eastern Time."""
    eastern = pytz.timezone('US/Eastern')
    return datetime.now(eastern).strftime('%Y-%m-%d')

def generate_sql_query(user_query, anthropic_client):
    """Generate SQL query using Claude based on natural language input."""
    
    # Get current date in Eastern Time
    current_date = get_current_eastern_date()
    
    schema = """
CREATE TABLE `combined-schedule` (
  `primary_key` varchar(16383) NOT NULL,
  `sport` varchar(16383),
  `level` varchar(16383),
  `league` varchar(16383),
  `date` date,
  `day` varchar(16383),
  `time` varchar(16383),
  `home_team` varchar(16383),
  `road_team` varchar(16383),
  `location` varchar(16383),
  `home_city` varchar(16383),
  `home_state` varchar(16383),
  PRIMARY KEY (`primary_key`)
)
"""
    
    example_query = """
SELECT league, `date`, day, `time`, home_team, road_team, location 
FROM `combined-schedule`
WHERE LOWER(home_state) IN (LOWER("NY"), LOWER("NJ"))
AND `date` >= '2024-12-19' AND `date` <= '2024-12-26'
ORDER BY `date`, `time` ASC
"""
    
    prompt = f"""You are a SQL expert. Given a natural language query, generate a valid SQL query for the following table schema:

{schema}

IMPORTANT: 
- Use absolute dates (e.g., '2024-12-19') instead of relative date functions like CURDATE(), DATE_ADD(), etc.
- Use case-insensitive string filtering with LOWER() function for text comparisons (e.g., LOWER(column) = LOWER('value'))

Current date (Eastern Time): {current_date}

Example of a valid SQL query using absolute dates and case-insensitive filtering:
{example_query}

User query: {user_query}

Generate a SQL query that answers the user's question. Use absolute dates in YYYY-MM-DD format and case-insensitive string filtering. Only return the SQL query, no explanations or markdown formatting."""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        sql_query = response.content[0].text.strip()
        # Remove any markdown formatting if present
        if sql_query.startswith("```sql"):
            sql_query = sql_query[6:]
        if sql_query.startswith("```"):
            sql_query = sql_query[3:]
        if sql_query.endswith("```"):
            sql_query = sql_query[:-3]
        
        return sql_query.strip()
        
    except Exception as e:
        print(f"Error generating SQL query: {e}")
        sys.exit(1)

def execute_sql_query(sql_query, owner, repo):
    """Execute SQL query against DoltHub repository."""
    
    # Construct the API URL
    api_url = f'https://www.dolthub.com/api/v1alpha1/{owner}/{repo}/main'
    
    print(f"Querying DoltHub repository: {owner}/{repo}")
    print(f"Generated SQL Query: {sql_query}")
    print("-" * 50)
    
    try:
        # Send the GET request to the DoltHub SQL API
        response = requests.get(api_url, params={'q': sql_query})
        
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the JSON response
            data = response.json()
            
            # Check for query execution errors
            if data.get('query_execution_status') == 'Error':
                print(f"SQL Error: {data.get('query_execution_message', 'Unknown error')}")
                return False
            
            # Extract and print the rows
            rows = data.get('rows', [])
            columns = data.get('columns', [])
            
            if rows:
                print(f"Found {len(rows)} rows:")
                print()
                
                # Print column headers
                if columns:
                    print("Columns:", " | ".join(columns))
                    print("-" * (len(" | ".join(columns)) + 10))
                
                # Print each row
                for i, row in enumerate(rows, 1):
                    print(f"Row {i}: {row}")
            else:
                print("No data found matching the query.")
                
        else:
            print(f'Error: HTTP {response.status_code}')
            print(f'Response: {response.text}')
            return False
            
    except requests.exceptions.RequestException as e:
        print(f'Network error: {e}')
        return False
    except json.JSONDecodeError as e:
        print(f'JSON parsing error: {e}')
        print(f'Raw response: {response.text}')
        return False
    except Exception as e:
        print(f'Unexpected error: {e}')
        return False
    
    return True

def main():
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Query sports schedules using natural language')
    parser.add_argument('query', nargs='?', default='Show me the first 4 games', 
                       help='Natural language query (default: "Show me the first 4 games")')
    parser.add_argument('--api-key', help='Anthropic API key (overrides .env file)')
    
    args = parser.parse_args()
    
    # Get API key
    api_key = args.api_key or os.getenv('API_KEY')
    if not api_key:
        print("Error: API_KEY not found in environment variables or --api-key argument")
        print("Please set API_KEY in your .env file or use --api-key argument")
        sys.exit(1)
    
    # Initialize Anthropic client
    anthropic_client = Anthropic(api_key=api_key)
    
    # Define the repository owner and name
    owner = 'gmichnikov'
    repo = 'sports-schedules'
    
    # Generate SQL query from natural language
    print(f"Natural language query: {args.query}")
    print("Generating SQL query...")
    sql_query = generate_sql_query(args.query, anthropic_client)
    
    # Execute the SQL query
    success = execute_sql_query(sql_query, owner, repo)
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
