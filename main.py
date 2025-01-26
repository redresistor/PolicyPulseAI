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
from dateutil import parser
import grapheme
import time
# from autogen_ext.models import OpenAIChatCompletionClient

import autogen
from datetime import datetime, timedelta, timezone

os.environ["AUTOGEN_USE_DOCKER"] = "False"  # Set to True if docker is available to run the generated code. Using docker is safer than running the generated code directly.

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
    url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    feed = feedparser.parse(url)
    entries = feed.entries
    cutoff_time = datetime.now() - timedelta(hours=hours)
    recent_entries = [entry for entry in entries if datetime(*entry.published_parsed[:6]) > cutoff_time]
    return recent_entries

def get_articles_from_rss(rss_url):
    """
    Fetches articles from the given RSS URL and returns those published within the last hour.
    
    Args:
        rss_url (str): The URL of the RSS feed.
    
    Returns:
        list: A list of article dictionaries.
    """
    try:
        # Fetch the RSS feed
        feed = feedparser.parse(rss_url)
        
        # Get the current timezone info
        tz = timezone.utc

        # Calculate one hour before now in UTC timezone
        now_utc = datetime.now(tz)
        last_run = now_utc - timedelta(hours=3)

        # Filter entries by date, converting to local time if necessary
        filtered_feed = []
        for entry in feed.entries:
            # Convert entry.published to the same timezone as last_hour (UTC)
            pubdate = parser.parse(entry.published)
            print("\n\n---\nentry.published: ", pubdate)
            print("entry.title was: ", entry.title)
            # print("text was: ", entry.text)
            if last_run.timestamp() <= pubdate.timestamp():
                filtered_feed.append(entry)
            print("\nfiltered feed was: \n", filtered_feed)
        return filtered_feed
    
    except Exception as e:
        print(f"Failed to fetch RSS: {e}")
        return None



def rss_searcher(url, hours=24):
    """
    Retrieves the last N hours of entries from an RSS feed.

    Args:
        url (str): The url of the RSS feed to be read from.
        last_n_hours (int, optional): The number of hours of entries to retrieve. Defaults to 24.
    Returns:
        data (dict): A dictionary containing the extracted entries from the RSS feed.
    """
    import feedparser
    url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    feed = feedparser.parse(url)

    entries = []
    if feed.status == 200:
        for entry in feed.entries:
            entries.append({
                    # 'text': entry.text,
                    'title': entry.title,
                    'date': entry.published,
                    'link': entry.link,
                    'author': entry.author,
                }
                )

    return {
                'entries': entries
            }


def extract_text_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove all script tags
    for script in soup(["script", "style"]):
        script.decompose()
    
    # Get the text content
    text = soup.get_text(separator=' ')
    
    # Remove extra whitespace
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    
    return text

# Function to extract news content from an article link
def extract_news_from_article(link):
    try:
        response = requests.get(link, allow_redirects=True)
        if response.status_code == 200:
            page_content = response.content
            return page_content.decode()  # Return the full HTML content as a string
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
        # print("link was: ", link)
        parsed = urlparse(link)
        actual_link = parse_qs(parsed.query)['url'][0]
        news_content = extract_news_from_article(actual_link) if 'youtube' not in actual_link else "YouTube video content"
        news_content = extract_text_from_html(news_content)

        chat = f"""Given the following content from a news article, ```Content: {news_content}```, please summarize 
        the actions of President Donald Trump and rate the impact of each action on a scale of 1-10. Give a very very brief analysis of how to counter act each action.
        Importantly, do not respond with any greetings or cordialities. Provide me only with the requested information in the form of:
        ```Act: [Action/Policy]
        Impact: [Rating]
        Analysis: [Your terse/concise analysis]```

        Please remember that the full content may be spread across
        many divs or spans, so you may need to extract the relevant information from the content.
        It'c critical that you keep your responses to no more than 300 characters.
        """

        chat_manager = autogen.GroupChatManager(groupchat)
        groupchat_result = user.initiate_chat(
            chat_manager, message=chat
        )
        

        summary = groupchat_result.chat_history[-1].get('content', '')

        splits = summary.split("Act:")
        print("link was: ", actual_link,"\n===========\n")
        
        url = 'http://tinyurl.com/api-create.php?url='
        # long_url = actual_link

        response = requests.get(url+actual_link)
        short_url = response.text
        for split in splits[1:]:
            summary = "This post generated by AI: \nLink: " + short_url + "\nAct: " + split
            summaries.append(summary)
            if len(summary) < 250:
                post_to_bluesky(summary, dry=True)
                time.sleep(5)
            else:
                print("\n\n------\nTOO LONG TO POST TO BLUESKY! SKIPPING: \n", summary, "\n\n=========\n")
    return summaries

# Function to post summary to BlueSky
def post_to_bluesky(content, dry=True):
    print("\n--\nPosting to BlueSky... \n", content)
    if not dry:
        BSKY_CLIENT.post(content)

# Main function
def main():
    rss_feed_url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    entries = get_articles_from_rss(rss_feed_url)
    summaries = analyze_and_summarize(entries)
    # post_to_bluesky(summaries)
    # print(summaries)

if __name__ == "__main__":
    main()