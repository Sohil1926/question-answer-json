import pandas as pd
#convert json to dataframe
   
data_frame = pd.read_json("member_info.json")


# Ensure 'referred_by' column is in the DataFrame and doesn't contain NaN values
if 'referred_by' in data_frame.columns:
    referred_counts = data_frame['referred_by'].value_counts(dropna=True)
    most_referrer = referred_counts.idxmax()
else:
    most_referrer = None
print('AVERAGE HEIGHT', most_referrer)