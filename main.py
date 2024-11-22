import feedparser
import requests
from datetime import datetime
import autogen
import feedparser
from atproto import Client, models
import requests
from bs4 import BeautifulSoup
import os


config_list = autogen.config_list_from_json(
    env_or_file="OAI_CONFIG_LIST.json",
    filter_dict={"model": ["llama31"]},  # comment out to get all
)
# Initialize autogen agents
llm_config = {"config_list": config_list, "cache_seed": 42}

# Initialize autogen agents
user_proxy = autogen.UserProxyAgent(
    name="User_proxy",
    system_message="A human admin.",
    code_execution_config={
        "last_n_messages": 2,
        "work_dir": "groupchat",
        "use_docker": False,
    },
    human_input_mode="TERMINATE",
)
coder = autogen.AssistantAgent(
    name="Coder",
    llm_config=llm_config,
)
pm = autogen.AssistantAgent(
    name="Product_manager",
    system_message="Creative in software product ideas.",
    llm_config=llm_config,
)
groupchat = autogen.GroupChat(agents=[user_proxy, coder, pm], messages=[], max_round=12)
manager = autogen.GroupChatManager(groupchat=groupchat, llm_config=llm_config)

# BlueSky credentials
BSKY_USER = os.Environ.get("BSKY_USER")
BSKY_PASS = os.Environ.get("BSKY_PASS")

# Set up the BlueSky client
BSKY_CLIENT = Client()
BSKY_CLIENT.login(BSKY_USER, BSKY_PASS)

# Function to parse RSS feed
def parse_rss_feed(url):
    feed = feedparser.parse(url)
    entries = feed.entries
    return entries

# Function to extract news content from an article link
def extract_news_from_article(link):
    response = requests.get(link)
    if response.status_code == 200:
        page_content = response.content
        soup = BeautifulSoup(page_content, 'html.parser')
        
        # Example: Extract the main content from a <div> with class 'article-content'
        article_content = soup.find('div', class_='article-content')
        if article_content:
            return article_content.get_text(strip=True)
        else:
            return "No article content found."
    else:
        return f"Failed to retrieve the article. Status code: {response.status_code}"

# Function to send data to autogen agents for analysis and summary
def analyze_and_summarize(entries):
    summaries = []
    for entry in entries:
        title = entry.title
        summary = entry.summary if 'summary' in entry else entry.content[0].value
        link = entry.link
        news_content = extract_news_from_article(link) if 'youtube' not in link else "YouTube video content"

        message = f"Title: {title}\nSummary: {summary}\nLink: {link}\nContent: {news_content}"
        
        result = user_proxy.initiate_chat(manager, message=f"Please analyze and summarize the following entry: \"{message}\"")
        print("SUMMARY WAS: ", result.summary)
        summaries.append(result.summary)
    return summaries

# Function to post summary to BlueSky
def post_to_bluesky(summaries):
    for summary in summaries:
        BSKY_CLIENT.post(summary)

# Main function
def main():
    rss_feed_url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    entries = parse_rss_feed(rss_feed_url)
    summaries = analyze_and_summarize(entries)
    post_to_bluesky(summaries)

if __name__ == "__main__":
    main()