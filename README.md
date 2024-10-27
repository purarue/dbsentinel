A counterpart to <https://purarue.xyz/mal_unapproved/>. That lists entries that have yet to be approved, denied entries and deleted entries

This is a work in progress, but the basics are up at <https://purarue.xyz/dbsentinel>

## Goals

- Index MyAnimeList approved and unapproved anime/manga
- Save/keep track of deleted/denied (user-submitted entries which are denied by MAL moderators because they dont meet site guidelines), so the data is not lost forever
- Let users login to upload XML files, do interesting things (e.g. finding which anime/manga they don't have on their list). Let them keep track of deleted/denied entries?

Data Sources:

- [mal-id-cache](https://github.com/purarue/mal-id-cache) git history, which is updated by [checker_mal](https://github.com/Hiyori-API/checker_mal). `checker_mal` also indexes the unapproved data, which this pings periodically to grab/find new approved entries from MAL
- [MyAnimeList](https://myanimelist.net/), obviously, which this archives data from

This is mostly meant to act as an public archive. Database guidelines are finicky and what is considered anime is not the same by all, so saving deleted and denied entries is useful for many reasons (re-submitting entries etc.)

### TODO:

- [x] refresh data based on last updated date
- [x] frontend in pheonix
  - [ ] register/login
  - [ ] moderators/trusted users
    - [ ] parse reasons for denials/deletions from thread/allow users to input
    - [ ] add frontend button to refresh data for entries
    - [ ] UI to force remove/ban an entry
  - [x] dashboard that shows stats etc.
  - [x] frontend to view approved/deleted/denied/unapproved entries
  - [x] add info on search page letting you know what each approved status means
  - [x] let page be ordered by when items were approved/deleted/denied (guess by metadata if not available)
  - [x] sort by member count
  - [x] dark mode
  - [ ] connect IDs to tmdb (manually, users can submit requests)
- [ ] API for deleted/denied/unapproved ids/name
- [ ] upload full API dump periodically to a public URL (w ids/names)
- [ ] queries should work on alternative titles as well
- [ ] discord notifications if database has not been updated in a while to check for glitches (only if a glitch happens again, have since updated how things happen)
- [ ] let user upload their MAL XML export, parse and save data from it to localStorage
- [ ] let user find entries that are not on their list
- [ ] classifying chinese/korean/japanese entries
  - [ ] can use [chiefs tags](https://myanimelist.net/blog/MasterDChief) to get a list of chinese/korean entries, set difference that with <https://myanimelist.net/clubs.php?cid=42215> and <https://myanimelist.net/clubs.php?cid=41909> to find out which ones aren't on MAL. Can update that once a week and let it just be a static HTML page, which club owner can reference to add new things
  - [ ] API which receives an ID and returns if its a donghua/aeni, can be used with a userscript to add a tag to the page
- [ ] integrate with [notify-bot](https://github.com/purarue/mal-notify-bot)
  - [x] refresh command refreshes both
  - [ ] so that sources added there get added to the website (also allow items which aren't in #feed -- so this can source anything) -- only show on website through a domain allowlist
- [ ] cache data for people

## Incomplete setup instructions:

- Check [app/settings.py](app/settings.py) for the required environment variables
- Create a venv at .venv: `python3 -m virtualenv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`
- [`checker_mal`](https://github.com/Hiyori-API/checker_mal) could be running on the same machine, if you want to keep an updated anime/manga ID list locally:
  - Can fill out `usernames.txt` with peoples list to check for new entries
  - If you have a `animelist.xml` file to use for `python3 main.py mal estimate-deleted-xml`, you can put it in `data/animelist.xml`
- `scripts/in_venv prod`
