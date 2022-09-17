# Development

This is a fork from [mp-eventwatcher](https://github.com/ccev/mp-eventwatcher) for personal changes and because coding is fun :). Changes / new features:

- (change) using own defined class for events (because I like it ;) )
- (change) only add spawn events as MAD event and add no lure duration only events
- (new feature) use of plugin pages to visualize current event data of plugin
- (new feature) Telegram notification on quest reset
- (new feature) delete quest table in case of quest reset instead of manipulate walker. You have to enable MAD to rescan quests by useful walker setting. Example walker setting:

| Area          | Area mode | Walker mode | Setting    |
| ------------- | --------- | ----------- | ---------- |
| quest_all     | pokestops | coords      | 1:00-6:00  |
| quest_rescan<sup>1</sup> | pokestops | coords      | 6:00-18:00 |
| pokemon       | mon_mitm  | period      | 1:10-1:00  |

<sup>1</sup>Area especially for quest rescan with limited devices/pokestops -> MAD will use this Area to rescan with e.g. smaller geofence or limited devices)

## Improvements

- Update lure duration for default event in case of not spawn changing event with lure duration != default lure duration ->  MAD ignores lure_duration setting for event 'DEFAULT' (see function _extract_args_single_stop() in [DbPogoProtoSubmit.py](https://github.com/Map-A-Droid/MAD/blob/master/mapadroid/db/DbPogoProtoSubmit.py))

# Usage

I don't provide a mp file. But you can easily install the plugin by clone this branch into your MAD/plugins/ folder:

- go to MAD/plugins: `cd <home?>/MAD/plugins`
- clone this branch: `git clone --branch v2refactor https://github.com/hamster007Github/mp-eventwatcher.git`
- go to new folder MAD/plugins/mp-eventwatcher/ and `cp plugin.ini.example plugin.ini`
- adapt MAD/plugins/mp-eventwatcher/plugin.ini for your needs
- Restart MAD

## plugin.ini options

**General**:

- `sleep` to define the time to wait in-between checking for new events. By default it's one hour.
- `delete_events` if you want Event Watcher to delete non-needed events (including basically all you've created yourself) - by default it's set to False.
- `max_event_duration` ignore events with duration longer than max_event_duration days. Set to 999 if you want to care also for session events

**Pokemon reset**:

- `reset_pokemon_enable` option to automatically delete obsolete pokemon from MAD database on start and end of pokemon changing event to enable MAD to rescan pokemon. true: enable function, false: disable function (default)
- `reset_pokemon_strategy` define pokemon delete strategy. ['all'(default) or 'filtered']
  - `all` delete all pokemon from databasse by SQL TRUNCATE query. Highly recommended for bigger instances
  - `filtered` delete only pokemon from database by SQL DELETE query, which are effected by eventchange. Can result in database lock issues (depends on server performance / database size
- `reset_pokemon_restart_app` restart pokemon go app on all devices on pokemon reset to flush encounter IDs in PD ['true' or 'false' (default)]

**Quest reset**:

- `reset_quests_enable` option to automatically delete quests from MAD database on start and/or end of quest changing event to enable MAD to rescan quests. true: enable function, false: disable function (default)
- `reset_quests_event_type` define event types and if you want quests to reset for their start, end or both.
  - `event community-day` - if you want to rescan quests for every start and end of an event and cday
  - `event:start` - only rescan quests for event starts (my personal recommendation)
  - `community-day event:end` - Rescan quests for cday starts and ends, but only for event ends
  - Available event types are `event`, `community-day`, `spotlight-hour` and `raid-hour`. The last 2 are less relevant. Most events are of type `event`.

**Telegram notification**:
This feature informs a user, group or channel about quest resets.

- `tg_info_enable` Enable or disable Telegram notification feature. ['true' or 'false' (default)]
- `tg_bot_token` Telegram bot API token from @godfather.
- `tg_chat_id` @username or id
- `quest_rescan_timewindow` timewindow with pattern ##-## (24h time format), in which quests are scanned. Used for inform Telegram users about possible rescan.
- `tg_str_questreset_before_scan` string which is posted additionally in configurated `tg_chat_id`, if quest reset happens before `quest_rescan_timewindow`. Will result in regular quest scan later.
- `tg_str_questreset_during_scan` string which is posted additionally in configurated `tg_chat_id`, if quest reset happens during `quest_rescan_timewindow`. Will result in quest rescan.
- `tg_str_questreset_after_scan` string which is posted additionally in configurated `tg_chat_id`, if quest reset happens after `quest_rescan_timewindow`. Will result in no quest rescan.

**Discord notification**:
This feature informs by webhook to a discord channel about quest resets.

- `dc_info_enable` Enable or disable Discord notification feature. ['true' or 'false' (default)]
- `dc_webhook_username` Discord Bot Username. ['Pogo Event Notification']
- `dc_webhook_url` Discord Webhook Url. [https://discordapp.com/api/webhooks/123456789/XXXXXXXXXXXXXXXXXXXXXXX]
- `dc_webhook_title` Discord Webhook Title for the embed. ['Event Quest notification']
  
# How does it work?

To not put unnecessary load on cool community-made websites, the Plugin pulls data from [this file](https://github.com/ccev/pogoinfo/blob/v2/active/events.json).

The Plugin then grabs that file and checks if an event is missing for you or changed information and then updates your database accordingly.

# Contact / Support

Please join [this discord](https://discord.gg/cMZs5tk)
