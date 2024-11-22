import feedparser
import requests
from datetime import datetime
import autogen
import feedparser
from atproto import Client, models

# from autogen import ConversableAgent, UserProxyAgent, AssistantAgent, GroupChat, config_list_from_json, GroupChatManager
# from autogen.coding import LocalCommandLineCodeExecutor, CodeBlock
# from rag import find_doc
config_list = autogen.config_list_from_json(
    env_or_file="OAI_CONFIG_LIST.json",
    filter_dict={"model": ["llama31"]},  # comment out to get all
)
# Initialize autogen agents
llm_config = {"config_list": config_list, "cache_seed": 42}
user_proxy = autogen.UserProxyAgent(
    name="User_proxy",
    system_message="A human admin.",
    code_execution_config={
        "last_n_messages": 2,
        "work_dir": "groupchat",
        "use_docker": False,
    },  # Please set use_docker=True if docker is available to run the generated code. Using docker is safer than running the generated code directly.
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
BSKY_USER = ""
BSKY_PASS = ""

# Set up the BlueSky client
BSKY_CLIENT = Client()
BSKY_CLIENT.login(BSKY_USER, BSKY_PASS)

# Function to parse RSS feed
def parse_rss_feed(url):
    feed = feedparser.parse(url)
    entries = feed.entries
    return entries

# Function to send data to autogen agents for analysis and summary
def analyze_and_summarize(entries):
    summaries = []
    for entry in entries:
        print("ENTRY WAS: ", entry)
        title = entry.title
        summary = entry.summary
        link = entry.link
        message = f"Title: {title}\nSummary: {summary}\nLink: {link}"

        result = user_proxy.initiate_chat(manager, message=f"Please analyze and summarize the following entry: \"{message}\"")
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