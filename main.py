import asyncio
import os
import shelve

from nextcord.ext import tasks
import aiohttp
import dotenv

dotenv.load_dotenv()

API_BASE_URL = "https://api.github.com/repos/{repo}/events"
REPO = "discord/discord-api-docs"
API_URL = API_BASE_URL.format(repo=REPO)
TOKEN = os.environ["GITHUB_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
DEFAULT_REF = "refs/heads/main"
SHELF = shelve.open("last_seen_event_id.db", writeback=True)


def make_payload(data):
    commits = ",".join(f"""{{
        "id": "{commit['sha']}",
        "message": "{commit['message'].replace("\n", r"\n")}",
        "url": "https://github.com/{data['repo']['name']}/commit/{commit['sha']}",
        "author": {{
            "name": "{commit['author']['name']}",
            "email": "{commit['author']['email']}"
        }}
    }}""" for commit in data['payload']['commits'])

    return f"""{{
        "ref": "{data['payload']['ref']}",
        "before": "{data['payload']['before']}",
        "after": "{data['payload']['head']}",
        "repository": {{
            "id": {data['repo']['id']},
            "name": "{data['repo']['name'].split('/')[1]}",
            "full_name": "{data['repo']['name']}",
            "owner": {{
                "name": "{data['repo']['name'].split('/')[0]}",
                "login": "{data['repo']['name'].split('/')[0]}",
                "html_url": "https://github.com/{data['repo']['name'].split('/')[0]}"
            }},
            "html_url": "https://github.com/{data['repo']['name']}"
        }},
        "sender": {{
            "login": "{data['actor']['login']}",
            "id": 1,
            "avatar_url": "{data['actor']['avatar_url']}",
            "html_url": "https://github.com/{data['actor']['login']}"
        }},
        "compare": "https://github.com/{data['repo']['name']}/compare/{data['payload']['before']}...{data['payload']['head']}",
        "commits": [{commits}],
        "head_commit": {{
            "id": "{data['payload']['commits'][0]['sha']}",
            "message": "{data['payload']['commits'][0]['message'].replace("\n", r"\n")}",
            "url": "https://github.com/{data['repo']['name']}/commit/{data['payload']['commits'][0]['sha']}",
            "author": {{
                "name": "{data['payload']['commits'][0]['author']['name']}",
                "email": "{data['payload']['commits'][0]['author']['email']}"
            }}
        }}
    }}"""



async def send_message(*, event, session: aiohttp.ClientSession):
    payload = make_payload(event)
    async with session.post(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-github-event": "push",
        },
    ) as webhook_response:
        if webhook_response.status == 204:
            print("Webhook sent successfully.")
        else:
            print(
                f"Failed to send webhook: {webhook_response.status} - {await webhook_response.text()}"
            )


@tasks.loop(seconds=60)
async def poll_commits(*, session: aiohttp.ClientSession):
    last_seen_event_id = SHELF.get("last_seen_event_id", None)
    if last_seen_event_id is None:
        print("No last seen event ID found, initializing.")
        last_seen_event_id = 0

    async with session.get(API_URL+"?per_page=100") as response:
        if response.status == 200:
            events = await response.json()
            push_events = [
                e for e in events if e.get("type") == "PushEvent" and e["payload"]["ref"] == DEFAULT_REF
            ]
            if not push_events:
                print("No new push events found.")
                return

            push_events.reverse()  # Oldest first.
            new_events = []
            for event in push_events:
                if "id" in event and int(event["id"]) > last_seen_event_id:
                    new_events.append(event)

            if not new_events:
                print("No new events since last check.")
                return

            SHELF["last_seen_event_id"] = last_seen_event_id = int(new_events[-1]["id"])
            SHELF.sync()

            for event in new_events:
                await send_message(event=event, session=session)
        else:
            print(f"Failed to fetch commits: {response.status} - {response.reason}")


async def main():
    async with aiohttp.ClientSession(
        headers={"Authorization": f"Bearer {TOKEN}"}
    ) as session:
        await poll_commits.start(session=session)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        poll_commits.stop()
