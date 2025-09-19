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
            model="claude-sonnet-4-20250514",  # Better for complex SQL generation
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

def generate_summary(query_results, user_query, anthropic_client):
    """Generate a summary of the query results using Claude."""
    
    # Format the results for the LLM
    if not query_results.get('rows'):
        return "No data found matching the query."
    
    rows = query_results.get('rows', [])
    columns = query_results.get('columns', [])
    
    # Create a formatted representation of the data
    data_summary = f"Query returned {len(rows)} rows with columns: {', '.join(columns)}\n\n"
    
    # Add all rows to the data summary
    for i, row in enumerate(rows, 1):
        data_summary += f"Row {i}: {row}\n"
    
    prompt = f"""You are a data analyst. Given the results of a database query, provide a succinct summary as bullet points.

Original user query: {user_query}

Query results:
{data_summary}

Format each row as a bullet point in this exact format:
• day date road team @ home team

For example:
• Friday 2024-04-05 Hartford @ Portland
• Friday 2024-04-05 New Hampshire @ Binghamton

Extract the day, date, road_team, and home_team from each row. Only return the bullet points, no explanations or other text."""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        summary = response.content[0].text.strip()
        return summary
        
    except Exception as e:
        print(f"Error generating summary: {e}")
        return "Unable to generate summary due to an error."

# ============================================================================
# TOOL DEFINITIONS FOR AGENTIC APPROACH
# ============================================================================

def analyze_question_tool(user_query, context, anthropic_client):
    """Tool: Analyze what the user wants to know and suggest next steps."""
    
    context_str = ""
    if context.get('results'):
        context_str = f"\nPrevious results: {len(context['results'])} queries executed so far."
    
    prompt = f"""You are a data analyst. Analyze this user query and suggest what information we need to gather.

User query: {user_query}
{context_str}

Based on the query, what specific information do we need to find? Be specific about what data points are required.

Respond with a JSON object like:
{{
    "analysis": "Brief description of what the user wants",
    "data_needed": ["specific data point 1", "specific data point 2"],
    "suggested_approach": "How to approach this query"
}}"""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = response.content[0].text.strip()
        return {"tool": "analyze_question", "result": result}
        
    except Exception as e:
        return {"tool": "analyze_question", "error": str(e)}

def execute_sql_tool(sql_query, owner, repo):
    """Tool: Execute SQL query and return results."""
    
    # Use existing execute_sql_query function but return structured data
    api_url = f'https://www.dolthub.com/api/v1alpha1/{owner}/{repo}/main'
    
    try:
        response = requests.get(api_url, params={'q': sql_query})
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('query_execution_status') == 'Error':
                return {"tool": "execute_sql", "error": data.get('query_execution_message', 'Unknown error')}
            
            rows = data.get('rows', [])
            columns = data.get('columns', [])
            
            return {
                "tool": "execute_sql", 
                "sql": sql_query,
                "rows": rows,
                "columns": columns,
                "row_count": len(rows)
            }
        else:
            return {"tool": "execute_sql", "error": f"HTTP {response.status_code}: {response.text}"}
            
    except Exception as e:
        return {"tool": "execute_sql", "error": str(e)}

def summarize_data_tool(data, anthropic_client):
    """Tool: Summarize data in bullet point format."""
    
    if not data.get('rows'):
        return {"tool": "summarize_data", "result": "No data to summarize"}
    
    rows = data.get('rows', [])
    columns = data.get('columns', [])
    
    # Create data summary for LLM
    data_summary = f"Query returned {len(rows)} rows with columns: {', '.join(columns)}\n\n"
    for i, row in enumerate(rows, 1):
        data_summary += f"Row {i}: {row}\n"
    
    prompt = f"""Format each row as a bullet point in this exact format:
• day date road team @ home team

Data:
{data_summary}

Extract the day, date, road_team, and home_team from each row. Only return the bullet points, no explanations."""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        summary = response.content[0].text.strip()
        return {"tool": "summarize_data", "result": summary}
        
    except Exception as e:
        return {"tool": "summarize_data", "error": str(e)}

def compare_data_tool(data1, data2, comparison_type, anthropic_client):
    """Tool: Compare two datasets."""
    
    prompt = f"""Compare these two datasets and provide insights.

Dataset 1: {data1.get('row_count', 0)} rows
Dataset 2: {data2.get('row_count', 0)} rows

Comparison type: {comparison_type}

Provide a brief comparison highlighting key differences or similarities."""

    try:
        response = anthropic_client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        comparison = response.content[0].text.strip()
        return {"tool": "compare_data", "result": comparison}
        
    except Exception as e:
        return {"tool": "compare_data", "error": str(e)}

def answer_question_tool(user_question, data, anthropic_client):
    """Tool: Analyze data and provide a direct answer to the user's question."""
    
    # Get current date in Eastern Time
    current_date = get_current_eastern_date()
    
    # Format the data for analysis
    if not data.get('rows'):
        data_summary = "No data available"
    else:
        rows = data.get('rows', [])
        columns = data.get('columns', [])
        data_summary = f"Found {len(rows)} rows with columns: {', '.join(columns)}\n\n"
        
        # Include sample data
        for i, row in enumerate(rows[:10], 1):  # First 10 rows
            data_summary += f"Row {i}: {row}\n"
        if len(rows) > 10:
            data_summary += f"... and {len(rows) - 10} more rows\n"
    
    prompt = f"""You are an expert data analyst. Based on the data provided, give a direct, helpful answer to the user's question.

User's question: {user_question}

Current date (Eastern Time): {current_date}

Available data:
{data_summary}

Instructions:
1. Analyze the data in relation to the user's question
2. Use the current date to understand temporal context (e.g., "next week", "today", etc.)
3. Provide a direct answer (yes/no, specific numbers, recommendations, etc.)
4. If the data doesn't fully answer the question, explain what's missing
5. Be specific and actionable
6. If it's a complex question, break it down and provide structured recommendations

Answer the user's question directly and helpfully."""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",  # Better for complex analysis
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        answer = response.content[0].text.strip()
        return {"tool": "answer_question", "result": answer}
        
    except Exception as e:
        return {"tool": "answer_question", "error": str(e)}

# Tool registry
AVAILABLE_TOOLS = {
    "analyze_question": analyze_question_tool,
    "execute_sql": execute_sql_tool,
    "summarize_data": summarize_data_tool,
    "compare_data": compare_data_tool,
    "answer_question": answer_question_tool
}

def agent_think(user_query, context, anthropic_client):
    """Agent decision engine: decides which tool to use next."""
    
    # Build context summary
    context_summary = f"Step {context.get('step', 0)}: "
    if context.get('results'):
        context_summary += f"Executed {len(context['results'])} tools so far. "
        
        # Check if we already have SQL data
        sql_results = [r for r in context['results'] if r['tool'] == 'execute_sql' and 'rows' in r]
        if sql_results:
            total_rows = sum(r.get('row_count', 0) for r in sql_results)
            context_summary += f"Already have {total_rows} rows of data from {len(sql_results)} SQL queries. "
        
        # Check if we already have summaries
        summary_results = [r for r in context['results'] if r['tool'] == 'summarize_data']
        if summary_results:
            context_summary += f"Already generated {len(summary_results)} summaries. "
        
        recent_results = context['results'][-2:]  # Last 2 results
        for result in recent_results:
            if 'error' in result:
                context_summary += f"Last tool ({result['tool']}) had error: {result['error']}. "
            else:
                context_summary += f"Last tool ({result['tool']}) succeeded. "
    else:
        context_summary += "Starting fresh. "
    
    # Available tools description
    tools_desc = """
Available tools:
- analyze_question: Analyze what the user wants to know
- execute_sql: Run SQL queries against the database
- summarize_data: Create bullet point summaries of data
- compare_data: Compare two datasets
- answer_question: Analyze data and provide a direct answer to the user's question
"""
    
    prompt = f"""You are an AI agent that helps users query sports schedule data. 

User query: {user_query}

{context_summary}

{tools_desc}

Based on the user query and current context, decide what to do next. 

Respond with a JSON object like:
{{
    "tool": "tool_name",
    "reasoning": "Why I'm choosing this tool",
    "params": {{
        "param1": "value1",
        "param2": "value2"
    }}
}}

If the task seems complete, respond with:
{{
    "tool": "done",
    "reasoning": "Task is complete",
    "params": {{}}
}}"""

    try:
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",  # Better for complex reasoning
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = response.content[0].text.strip()
        
        # Try to parse JSON response
        try:
            import json
            # Clean up the response to extract JSON
            if "```json" in result:
                result = result.split("```json")[1].split("```")[0].strip()
            elif "```" in result:
                result = result.split("```")[1].split("```")[0].strip()
            
            decision = json.loads(result)
            return decision
        except json.JSONDecodeError as e:
            # Fallback if JSON parsing fails - try to extract tool name from text
            if "summarize_data" in result.lower():
                return {
                    "tool": "summarize_data",
                    "reasoning": "Detected summarize_data from text",
                    "params": {}
                }
            elif "execute_sql" in result.lower():
                return {
                    "tool": "execute_sql", 
                    "reasoning": "Detected execute_sql from text",
                    "params": {}
                }
            elif "done" in result.lower() or "complete" in result.lower():
                return {
                    "tool": "done",
                    "reasoning": "Detected completion from text", 
                    "params": {}
                }
            else:
                return {
                    "tool": "summarize_data",
                    "reasoning": f"Failed to parse JSON, defaulting to summarize_data. Error: {str(e)}",
                    "params": {}
                }
        
    except Exception as e:
        return {
            "tool": "analyze_question", 
            "reasoning": f"Error in agent_think: {str(e)}",
            "params": {}
        }

def execute_tool_decision(decision, context, owner, repo, anthropic_client):
    """Execute a tool based on agent decision."""
    
    tool_name = decision.get("tool")
    params = decision.get("params", {})
    
    if tool_name == "done":
        return {"tool": "done", "result": "Task completed"}
    
    if tool_name not in AVAILABLE_TOOLS:
        return {"tool": tool_name, "error": f"Unknown tool: {tool_name}"}
    
    tool_func = AVAILABLE_TOOLS[tool_name]
    
    try:
        if tool_name == "analyze_question":
            return tool_func(context.get("original_query", ""), context, anthropic_client)
        elif tool_name == "execute_sql":
            # Generate SQL query first if not provided
            if "sql_query" not in params:
                user_query = context.get("original_query", "")
                sql_query = generate_sql_query(user_query, anthropic_client)
                print(f"🔍 Generated SQL: {sql_query}")
            else:
                sql_query = params.get("sql_query", "")
            return tool_func(sql_query, owner, repo)
        elif tool_name == "summarize_data":
            # Get the most recent SQL result if no data provided
            if "data" not in params:
                sql_results = [r for r in context["results"] if r["tool"] == "execute_sql" and "rows" in r]
                if sql_results:
                    data = sql_results[-1]  # Use most recent SQL result
                else:
                    data = {}
            else:
                data = params.get("data", {})
            return tool_func(data, anthropic_client)
        elif tool_name == "compare_data":
            data1 = params.get("data1", {})
            data2 = params.get("data2", {})
            comparison_type = params.get("comparison_type", "general")
            return tool_func(data1, data2, comparison_type, anthropic_client)
        elif tool_name == "answer_question":
            # Get the most recent SQL result if no data provided
            if "data" not in params:
                sql_results = [r for r in context["results"] if r["tool"] == "execute_sql" and "rows" in r]
                if sql_results:
                    data = sql_results[-1]  # Use most recent SQL result
                else:
                    data = {}
            else:
                data = params.get("data", {})
            user_question = context.get("original_query", "")
            return tool_func(user_question, data, anthropic_client)
        else:
            return {"tool": tool_name, "error": f"No handler for tool: {tool_name}"}
            
    except Exception as e:
        return {"tool": tool_name, "error": str(e)}

def agent_loop(user_query, owner, repo, anthropic_client):
    """Main agent loop that keeps running until task is complete."""
    
    context = {
        "original_query": user_query,
        "step": 0,
        "results": [],
        "data_cache": {}  # Store data for potential reuse
    }
    
    max_steps = 10  # Prevent infinite loops
    print(f"🤖 Agent starting with query: {user_query}")
    print("=" * 60)
    
    while context["step"] < max_steps:
        context["step"] += 1
        print(f"\n🔄 Step {context['step']}: Thinking...")
        
        # Agent decides what to do next
        decision = agent_think(user_query, context, anthropic_client)
        print(f"💭 Decision: {decision.get('reasoning', 'No reasoning provided')}")
        
        # Check if task is complete
        if decision.get("tool") == "done":
            print("✅ Task completed!")
            break
        
        # Execute the tool
        print(f"🔧 Executing tool: {decision.get('tool')}")
        result = execute_tool_decision(decision, context, owner, repo, anthropic_client)
        
        # Store result
        context["results"].append(result)
        
        # Handle errors
        if "error" in result:
            print(f"❌ Error: {result['error']}")
            if context["step"] >= 3:  # Stop after 3 errors
                print("🛑 Too many errors, stopping.")
                break
        else:
            print(f"✅ Tool {result['tool']} completed successfully")
            
            # Display tool results
            if result["tool"] == "analyze_question":
                print(f"📋 Analysis: {result.get('result', 'No analysis provided')}")
            elif result["tool"] == "execute_sql":
                rows = result.get('rows', [])
                columns = result.get('columns', [])
                print(f"📊 Query returned {len(rows)} rows")
                if rows:
                    print("Columns:", " | ".join(columns))
                    print("-" * 50)
                    for i, row in enumerate(rows[:5], 1):  # Show first 5 rows
                        print(f"Row {i}: {row}")
                    if len(rows) > 5:
                        print(f"... and {len(rows) - 5} more rows")
            elif result["tool"] == "summarize_data":
                print(f"📝 Summary: {result.get('result', 'No summary provided')}")
            elif result["tool"] == "compare_data":
                print(f"⚖️ Comparison: {result.get('result', 'No comparison provided')}")
            elif result["tool"] == "answer_question":
                print(f"💡 Answer: {result.get('result', 'No answer provided')}")
            
            # Cache data for potential reuse
            if result["tool"] == "execute_sql" and "rows" in result:
                context["data_cache"][f"query_{len(context['results'])}"] = result
    
    # Generate final summary
    print("\n" + "=" * 60)
    print("📊 FINAL SUMMARY")
    print("=" * 60)
    
    # Find all successful SQL results
    sql_results = [r for r in context["results"] if r["tool"] == "execute_sql" and "rows" in r]
    
    if sql_results:
        # Combine all SQL results
        all_rows = []
        all_columns = []
        for result in sql_results:
            all_rows.extend(result.get("rows", []))
            if not all_columns and result.get("columns"):
                all_columns = result["columns"]
        
        combined_data = {
            "rows": all_rows,
            "columns": all_columns
        }
        
        # Generate summary
        summary_result = summarize_data_tool(combined_data, anthropic_client)
        if "result" in summary_result:
            print(summary_result["result"])
        else:
            print("Unable to generate summary")
    else:
        print("No data found to summarize")
    
    return context

def execute_sql_query(sql_query, owner, repo):
    """Execute SQL query against DoltHub repository and return results."""
    
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
                return None
            
            # Extract the rows and columns
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
            
            # Return the data for summary generation
            return data
                
        else:
            print(f'Error: HTTP {response.status_code}')
            print(f'Response: {response.text}')
            return None
            
    except requests.exceptions.RequestException as e:
        print(f'Network error: {e}')
        return None
    except json.JSONDecodeError as e:
        print(f'JSON parsing error: {e}')
        print(f'Raw response: {response.text}')
        return None
    except Exception as e:
        print(f'Unexpected error: {e}')
        return None

def main():
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Query sports schedules using natural language')
    parser.add_argument('query', nargs='?', default='Show me the first 4 games', 
                       help='Natural language query (default: "Show me the first 4 games")')
    parser.add_argument('--api-key', help='Anthropic API key (overrides .env file)')
    parser.add_argument('--agent', action='store_true', 
                       help='Use agentic approach (multiple queries, adaptive planning)')
    
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
    
    if args.agent:
        # Use agentic approach
        agent_loop(args.query, owner, repo, anthropic_client)
    else:
        # Use original approach
        print(f"Natural language query: {args.query}")
        print("Generating SQL query...")
        sql_query = generate_sql_query(args.query, anthropic_client)
        
        # Execute the SQL query
        query_results = execute_sql_query(sql_query, owner, repo)
        
        if query_results is None:
            sys.exit(1)
        
        # Generate and display summary
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print("Generating summary...")
        
        summary = generate_summary(query_results, args.query, anthropic_client)
        print(summary)

if __name__ == "__main__":
    main()
