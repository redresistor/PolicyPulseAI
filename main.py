import feedparser
import requests
from autogen import config_list_from_json
import feedparser
from atproto import Client, models
import requests
from bs4 import BeautifulSoup
import os
from dataclasses import dataclass
from autogen_core.application import SingleThreadedAgentRuntime
from urllib.parse import urlparse
from urllib.parse import parse_qs
# from autogen_ext.models import OpenAIChatCompletionClient

import autogen
from datetime import datetime, timedelta

config_list = config_list_from_json(
    env_or_file="OAI_CONFIG_LIST.json",
    filter_dict={"model": ["llama31"]},  # comment out to get all
)

# Initialize autogen agents
llm_config = {"config_list": config_list, "cache_seed": 42}

# Initialize runtime and assistants
runtime = SingleThreadedAgentRuntime()

user = autogen.UserProxyAgent(
    name="User",
    llm_config=llm_config,
)

evaluator = autogen.AssistantAgent(
    name="Evaluator",
    llm_config=llm_config,
    system_message="""You are the Evaluator. Your only job is to evalute the summary of an article and the original 
    article to ensure the summary is accurate.
    Additionally, you are able to use your understanding of government policy and workings, as well as your understanding of
    how democracy works, to provide suggested actions to take to counter the impact of the policy or action.""",
)

summarizer = autogen.UserProxyAgent(
    name="Summarizer",
    llm_config=llm_config,
    system_message="""You are the Summarizer. You take an article or piece of content and summarize it. You primarily are 
    concerned with summarzing the actions of President Donald Trump to extract the most impactful pieces of information from the content.
    You will also rate the impact of each action or policy on a scale of 1-10.""",
    human_input_mode="NEVER",
    # code_execution_config={
    #     "last_n_messages": 5,
    #     # "work_dir": "paper",
    #     # llm_config=llm_config,
    #     "use_docker": False,
    # },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
)

def state_transition(last_speaker, groupchat):
    # messages = groupchat.messages

    if last_speaker is user:
        # init -> retrieve
        return summarizer
    elif last_speaker == "Summarizer":
        return evaluator
    elif last_speaker == "Evaluator":
        # research -> end
        return None


groupchat = autogen.GroupChat(
    agents=[user, summarizer, evaluator],
    messages=[],
    max_round=5,
    speaker_selection_method=state_transition,
)
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)

# BlueSky credentials
env = os.environ
BSKY_USER = env.get("BSKY_USER")
BSKY_PASS = env.get("BSKY_PASS")

# Set up the BlueSky client
BSKY_CLIENT = Client()
BSKY_CLIENT.login(BSKY_USER, BSKY_PASS)

# Function to parse RSS feed and filter entries from the last N hours
def parse_rss_feed(url, hours=24):
    feed = feedparser.parse(url)
    entries = feed.entries
    cutoff_time = datetime.now() - timedelta(hours=hours)
    recent_entries = [entry for entry in entries if datetime(*entry.published_parsed[:6]) > cutoff_time]
    return recent_entries

# Function to extract news content from an article link
def extract_news_from_article(link):
    try:
        response = requests.get(link, allow_redirects=True)
        if response.status_code == 200:
            page_content = response.content
            return page_content.decode('utf-8')  # Return the full HTML content as a string
        else:
            return f"Failed to retrieve the article. Status code: {response.status_code}"
    except requests.RequestException as e:
        return f"An error occurred: {e}"

# Function to send data to autogen agents for analysis and summary
def analyze_and_summarize(entries):
    summaries = []
    for entry in entries:
        # title = entry.title
        # # summary = entry.summary if 'summary' in entry else entry.content[0].value
        link = entry.link
        print("link was: ", link)
        parsed = urlparse(link)
        actual_link = parse_qs(parsed.query)['url'][0]
        news_content = extract_news_from_article(actual_link) if 'youtube' not in actual_link else "YouTube video content"

        chat = f"""Given the following HTML content, ```Content: {news_content}```, please summarize 
        the actions of President Donald Trump and rate the impact of each action on a scale of 1-10.
        Importantly, do not respond with any greetings or cordialities. Provide me only with the requested information in the form of:
        Action/Policy: [Action/Policy]
        Impact: [Rating]
        Recommendation: [Recommendation]

        in a well-formatted JSON response, if you can. Please remember that the full content may be spread across
        many divs or spans, so you may need to extract the relevant information from the content.
        """

        chat_manager = autogen.GroupChatManager(groupchat)
        groupchat_result = user.initiate_chat(
            chat_manager, message=chat
        )
        
        summaries.append(groupchat_result)  # Store the result in summaries
    return summaries

# Function to post summary to BlueSky
def post_to_bluesky(summaries):
    print("Posting to BlueSky...")
    for summary in summaries:
        BSKY_CLIENT.post(summary)

# Main function
def main():
    rss_feed_url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    entries = parse_rss_feed(rss_feed_url, hours=24)  # Adjust the hours as needed
    summaries = analyze_and_summarize(entries)
    # post_to_bluesky(summaries)
    print(summaries)

if __name__ == "__main__":
    main()