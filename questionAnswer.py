import json 
from dotenv import load_dotenv, find_dotenv
import os.path
import pandas as pd
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

#load env
dotenv_path = find_dotenv()
load_dotenv(dotenv_path)

OpenAI.api_key = os.getenv("OPENAI_API_KEY")

client = OpenAI()

#1st retry, 4 seconds, 2nd retry 1 * 2^2 (max 10 sec), 3rd 10 sec
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def call_openai(prompt:str) -> str:
    try: 
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ]
        )
    # print(response.choices[0].message.content)
        return response
    except Exception as e:
        print(f"Error calling OpenAI API: {str(e)}")
        raise

#flatten a nested column in the dataframe if it exists.
def get_metadata_columns(data_frame, column_name='metadata'):
    if column_name in data_frame.columns:
        # convert stringified JSON to dict 
        if isinstance(data_frame[column_name].iloc[0], str):
            data_frame[column_name] = data_frame[column_name].apply(lambda x: json.loads(x) if isinstance(x, str) else x)
        # flatten the dictionary into separate columns
        metadata_df = data_frame[column_name].apply(pd.Series)
        # drop the original metadata column and concatenate the new columns with the original dataframe
        data_frame = pd.concat([data_frame.drop(columns=[column_name]), metadata_df], axis=1)
    return data_frame

def summarize_output(query: str, pandas_code: str, output: str) -> str:
    summarize_prompt = f"""
    The user asked the following question: "{query}"

    To answer this question, the following Pandas code in python was generated and executed:
    {pandas_code}

    The output of this code was:
    {output}

    Please provide a clear, concise summary that answers the user's question based on this information. 
    The summary should be in plain language, avoiding technical jargon where possible. 
    If there are any limitations or caveats to the answer based on the available data, please mention them briefly.
    """

    try:
        response = call_openai(summarize_prompt)
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Error summary: {str(e)}"
    
def run_qa(file_path: str, query: str) -> str: 
    #FILE STUFF
    #check if file exists
    if not os.path.isfile(file_path):
        print("File path not found")
        return 
    
    #convert json to dataframe
    data_frame = pd.read_json(file_path)
    
    #Flatten the metadata column if it exists
    data_frame = get_metadata_columns(data_frame, column_name='metadata')
    data_frame.to_csv('output.csv', index=False)
    #store column names 
    column_names = data_frame.columns.tolist()
    print(column_names)
   
    # ask user if column names are as expected
    correct_columns = input("Correct column names (y/n)?")
    if(correct_columns == 'n'):
        return "Incorrect column names. Exiting..."
    
    #get the first 200 rows of dataframe for context
    df_head = data_frame.head(200).to_string()

    #FIND WHAT DATA USER IS ASKING FOR
    # Construct the prompt for GPT
    prompt = f"""
    Here are the column names available in our DataFrame: {column_names}. 
    Here is what the first few rows of the DataFrame look like: {df_head}
    The user asked: {query}.
    Please note that some rows can have values that are empty (nan).
    Do not explain anything. Determine if the query is relevant to the columns in the dataframe (values can be nan). If it is relevant, output only the relevant column(s) seperated by commas from the columns avaliable in the dataframe to answer the query.
    If it is not relevant output NOT RELEVANT.
    """

    response = call_openai(prompt)
    column_names_from_prompt = [name.strip() for name in response.choices[0].message.content.split(',')]
    
    print("COLUMN NAME(S) FROM PROMPT: " , column_names_from_prompt)

    #check if column name from prompt in column_names
    # if not all(column in column_names for column in column_names_from_prompt):
    #     print("I cannot answer the query using the information from the file")
    #     return 

    if(column_names_from_prompt[0] == "NOT RELEVANT"):
        print("I cannot answer the query using the information from the file")
        return
    
    #get the first 200 rows of dataframe for context
    df_head = data_frame.head(200).to_string()

    # print('HEAD', df_head)
    
    #PROMPT GPT TO GENERATE A PANDAS QUERY TO ANSWER THE USER QUERY
    operation_prompt = f"""
    Based on the query: '{query}', generate the corresponding Pandas code to perform the operation on the columns: {column_names}.
    Here is what the first few rows of the DataFrame look like:
    {df_head}

    Assume that the DataFrame variable is called 'data_frame'.
    Please note:
    - Let's think step by step for each query
    - Any row can have a missing value in the column (nan)
    - Only use the column names that exist in the DataFrame.
    - Ensure that the code is robust and handles potential edge cases (e.g., different date formats).
    - Do not include any print statements, and do not output any explanations. DO NOT DESCRIBE THE CODE. 
    - Do not create any sample DataFrame for demonstration using the rows of the dataframe I included in this prompt, this query will later by executed on the data_frame variable
    - Here are some synonyms for the column names: France = French 
    - Whenever filtering for any particular column only use the ones avaliable in {column_names}
    - Lastly, for any queries dealing with error log dataframes, make sure the pandas query that is generated saves a new a csv file of the related dataframe.
    """

    pandas_query = call_openai(operation_prompt)
    # print("PANDAS QUERY" , pandas_query)

    #format and print pandas query
    formatted_code = pandas_query.choices[0].message.content.replace("```python", "").replace("```", "").strip()
    print("Generated Pandas Query:", formatted_code)

    # execute the formatted Pandas query
    try:
        # local scope dict to store the results
        local_scope = {"data_frame": data_frame}
        # execute the generated code, no global variables
        exec(formatted_code, {}, local_scope)
        #retain only the output
        result_vars = {k: v for k, v in local_scope.items() if k not in ["data_frame"]}
        # for var_name, value in result_vars.items():
            # print(f"{var_name}: {value}")
        output = "\n".join([f"{k}: {v}" for k, v in result_vars.items()])
        summary = summarize_output(query, formatted_code, output)
        print("\nSummarized Output: ", summary)
            
    except Exception as e:
        print(f"Error executing the query: {str(e)}")

#example query
# run_qa('error_logs.json', 'Which users are most frequently encountering errors, and what are the most common stack traces they experience?')
run_qa('member_info.json', 'Who referred the most number of members?')
