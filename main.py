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
import time
import sys
from typing import List, Dict
import re

# from autogen_ext.models import OpenAIChatCompletionClient

import autogen
from datetime import datetime, timedelta, timezone
import pytz

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
    You will also rate the impact of each action or policy on a scale of 1-10. You will never ever need to execute any code.""",
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
bsky_client = Client()
bsky_client.login(BSKY_USER, BSKY_PASS)

# Function to parse RSS feed and filter entries
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
        tz = pytz.timezone('EST')  # Change this to the appropriate timezone if needed

        # Calculate one hour before now in UTC timezone
        now_utc = datetime.now(tz)
        last_run = now_utc - timedelta(hours=3)

        # Filter entries by date, converting to local time if necessary
        filtered_feed = []
        log = False
        for entry in feed.entries:
            # Skip youtube links
            if 'youtube.com' in entry.link:
                # print("************* Skipping youtube link: ", entry.link, "*************")
                continue
            # Convert entry.published to the same timezone as last_hour (UTC)
            pubdate = parser.parse(entry.published)
            if log:
                print("--------\nJust got an article_from_rss feed!!")
                print("entry.title was: ", entry.title)
                print("entry.link was: ", entry.link)
                print("now_utc was: ", now_utc)
                print("pub_date.timestamp() was: ", pubdate.timestamp(), " | pub_date was: ", pubdate)
                print("last_run.timestamp() was: ", last_run.timestamp(), " | last_run was: ", last_run)
                print("conditional is last_run.timestamp() >= pubdate.timestamp()")
            if pubdate.timestamp() >= last_run.timestamp():
                filtered_feed.append(entry)
            # print("\nfiltered feed was: \n", filtered_feed)
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
def analyze_and_summarize(entries, dry=True):
    summaries = []
    for entry in entries:
        # title = entry.title
        # # summary = entry.summary if 'summary' in entry else entry.content[0].value
        link = entry.link
        # print("link was: ", link)
        parsed = urlparse(link)
        actual_link = parse_qs(parsed.query)['url'][0]

        # If it's a youtube link, skip to the next entry.
        if 'youtube' in actual_link:
            continue

        news_content = extract_news_from_article(actual_link)
        news_content = extract_text_from_html(news_content)

        chat = f"""Given the following content from a news article, ```Content: {news_content}```, please summarize 
        the actions of President Donald Trump and rate the impact of each action on a scale of 1-10. Give a very very brief analysis of how to counter act each action.
        Importantly, do not respond with any greetings or cordialities. Provide me with the requested analysis in the form of:

        [YOUR SUMMARY]
        **Analysis header here**
        '''
        Act: [ACTION/POLICY]
        Impact: [RATING]/10
        Analysis: [YOUR TERSE/CONCISE ANALYSIS]
        Potential counters: [SUGGESTED ACTIONS]'''

        Make sure you introduce the SUMMARIES with an opening paragraph of no more than 2 very short sentence in which you describe the overall 
        content of the article, and the biggest takeaways, and nothing more.
        It's critical that you keep your response for each SUMMARY to no more than 250 characters, as well as the introductory summary. Make sure each
        individual summary is headered by **Summary 1**, **Summary 2**, etc.

        In its entirety, your response should look something like this:

        '''
        [INTRODUCTORY SUMMARY OF 2 SENTENCES]

        **Summary 1**
        Act: [ACTION/POLICY]
        Impact: [RATING]/10
        Analysis: [YOUR TERSE/CONCISE ANALYSIS]
        Potential counters: [SUGGESTED ACTIONS]

        **Summary 2**
        Act: [ACTION/POLICY]
        Impact: [RATING]/10
        Analysis: [YOUR TERSE/CONCISE ANALYSIS]
        Potential counters: [SUGGESTED ACTIONS]
        '''
        """

        chat_manager = autogen.GroupChatManager(groupchat)
        groupchat_result = user.initiate_chat(
            chat_manager, message=chat
        )
        

        summary = groupchat_result.chat_history[-1].get('content', '')

        splits = re.split(r'\*\*Summary \d+\*\*', summary)
        print("link was: ", actual_link, "\n===========\n")

        url = 'http://tinyurl.com/api-create.php?url='

        tinyurl_response = requests.get(url + actual_link)
        short_url = tinyurl_response.text
        index = 0
        parent = None
        root = None
        for split in splits:
            if split == '':
                continue

            if index == 0:
                print("\n\n----\nroot was: ", root)
                summary = "*Post generated by AI*\nLink: " + short_url + "\nDate: " + entry.published + "\n" + split
                summaries.append(summary)
                if len(summary) < 250:
                    post = bsky_client.send_post(text=summary)
                    root = models.create_strong_ref(post)
                    parent = models.create_strong_ref(post)
                else:
                    for i in range(0, len(summary), 250):
                        sub_summary = summary[i:i + 250]
                        if i == 0:
                            post = bsky_client.send_post(sub_summary)
                            root = models.create_strong_ref(post)
                            parent = models.create_strong_ref(post)
                        else:
                            post = bsky_client.send_post(sub_summary, reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent, root=root))
                            parent = models.create_strong_ref(post)
                time.sleep(5)
            else:
                print("\n\n----\nparent was: ", parent)
                print("root was: ", root)
                summary = "*Post generated by AI*\nLink: " + short_url + "\nDate: " + entry.published + "\n" + split
                if len(summary) < 250:
                    post = bsky_client.send_post(text=summary, reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent, root=root))
                    parent = models.create_strong_ref(post)
                else:
                    for i in range(0, len(summary), 250):
                        sub_summary = summary[i:i + 250]
                        post = bsky_client.send_post(sub_summary, reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent, root=root))
                        parent = models.create_strong_ref(post)
                time.sleep(5)
            index += 1
    return summaries

# Function to post summary to BlueSky
def post_to_bluesky(content, parent, root, dry=True) -> models.AppBskyFeedPost.CreateRecordResponse:
    print("\n--\nPosting to BlueSky... \n", content)
    if not dry:
        if parent is not None and root is not None:
            print("\n---------\nhad root and parent")
            resp = bsky_client.send_post(
                text=content,
                reply_to=models.AppBskyFeedPost.ReplyRef(parent=parent, root=root),
                )
        else:
            print("\n---------\nno root or parent")
            resp = bsky_client.send_post(
                text=content,
                )
        return resp
    return None

# Main function
def main():
    dry = sys.argv[1] if len(sys.argv) > 1 else True
    rss_feed_url = "https://www.google.com/alerts/feeds/14842518841889673538/2294658301143024541"
    entries = get_articles_from_rss(rss_feed_url)
    summaries = analyze_and_summarize(entries, dry=True)
    # post_to_bluesky("Test!", dry=False)
    # post_to_bluesky(summaries)
    # print(summaries)

if __name__ == "__main__":
    main()