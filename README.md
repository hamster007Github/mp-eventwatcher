## Development
This is a fork from [mp-eventwatcher](https://github.com/ccev/mp-eventwatcher) for personal changes and because coding is fun :). Changes:
- using own defined class for events (because I like it ;) )
- use of plugin pages to visualize current event data of plugin
- Only delete quest table in chase of quest reset instead of manipulate walker. Easier for small setups (use of rescan area in walker setting). Example walker setting:
  1. Area: quest_all / coords / 1:00-6:00
  2. Area: quest_rescan / coords / 6:00-18:00  (if quest are deleted during this time window -> MAD will use this Area to rescan with e.g. smaller geofence or limited devices)
  3. Area: pokemon / period / 1:10-1:00


### Improvements

Possible improvements that I've thought of
- Better documentation. I think a lot of people don't understand what Event Watcher does or how it should be configured
- Possibly an optional Raid Boss prediction. Instead of writing an egg to the DB, it could write the current boss to it. I tried implementing this but it got super hacky. maybe there's a better solution than what I had.
- Update lure duration for default event in case of not spawn changing event with lure duration != default lure duration

## Usage:
You can import this like any other MAD Plugin.

If this is the first time you're setting up a MAD Plugin:
- Download Eventwatcher.mp on the [releases page](https://github.com/ccev/mp-eventwatcher/releases)
- Open {madmin.com}/plugins, click "Choose file" and choose the EventWatcher.mp file you just downloaded. Or drag&drop it there.
- go to MAD/plugins/EventWatcher/ and `cp plugin.ini.example plugin.ini`
- adapt plugin.ini for your needs
- Restart MAD

There are following config options:
- `sleep` to define the time to wait in-between checking for new events. By default it's one hour.
- `delete_events` if you want Event Watcher to delete non-needed events (including basically all you've created yourself) - by default it's set to False.
- `max_event_duration` ignore events with duration longer than max_event_duration days. Set to 999 if you want to care also for session events
- `reset_pokemon_enable` option to automatically delete obsolete pokemon from MAD database on start and end of pokemon changing event to enable MAD to rescan pokemon. true: enable function, false: disable function (default)
- `reset_pokemon_truncate` option to use TRUNCATE SQL query instead of DELETE. Recommended for bigger instances. true: use TRUNCATE, false: use DELETE (default)
- `reset_quests_enable` option to automatically delete quests from MAD database on start and/or end of quest changing event to enable MAD to rescan quests. true: enable function, false: disable function (default)
- `reset_quests_event_type` define event types and if you want quests to reset for their start, end or both.
  - `event community-day` - if you want to rescan quests for every start and end of an event and cday
  - `event:start` - only rescan quests for event starts (my personal recommendation)
  - `community-day event:end` - Rescan quests for cday starts and ends, but only for event ends
  - Available event types are `event`, `community-day`, `spotlight-hour` and `raid-hour`. The last 2 are less relevant. Most events are of type `event`.

please also join [this discord](https://discord.gg/cMZs5tk)

## How does it work?
To not put unnecessary load on cool community-made websites, the Plugin pulls data from [this file](https://github.com/ccev/pogoinfo/blob/v2/active/events.json). A list I automatically update and commit to github.

The Plugin then grabs that file and checks if an event is missing for you or changed information and then updates your database accordingly.