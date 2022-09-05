import os
import requests
import json
import time
import re
import urllib
from threading import Thread
from flask import render_template, Blueprint, jsonify
from datetime import datetime, timedelta

from mapadroid.madmin.functions import auth_required
import mapadroid.utils.pluginBase

DEFAULT_LURE_DURATION = 30
DEFAULT_TIME = datetime(2030, 1, 1, 0, 0, 0)


class SimpleTelegramApi:
    def __init__(self, api_token):
        self._base_url = self._get_base_url(api_token)

    def _get_base_url(self, api_token):
        return "https://api.telegram.org/bot{}/".format(api_token)

    def _send_request(self, command):
        request_url = self._base_url + command
        #print(f"Send_Request:{command}")
        response = requests.get(request_url)
        decoded_response = response.content.decode("utf8")
        return decoded_response

    def send_message(self, chat_id, text, parse_mode="HTML"):
        text = urllib.parse.quote_plus(text)
        response = self._send_request("sendMessage?text={}&chat_id={}&parse_mode={}".format(text, chat_id, parse_mode))
        response = json.loads(response)
        return response

    def edit_message(self, chat_id, message_id, text, parse_mode="HTML"):
        text = urllib.parse.quote_plus(text)
        response = self._send_request("editMessageText?chat_id={}&message_id={}&parse_mode={}&text={}".format(chat_id, message_id, parse_mode, text))
        response = json.loads(response)
        # if edit a message with same text, you will get 'error_code': 400, 'description': 'Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message'
        return response

    def delete_message(self, chat_id, message_id):
        response = self._send_request("deleteMessage?chat_id={}&message_id={}".format(chat_id, message_id))
        response = json.loads(response)
        return response

    def pin_message(self, chat_id, message_id, disable_notification="True"):
        response = self._send_request("pinChatMessage?chat_id={}&message_id={}&disable_notification={}".format(chat_id, message_id, disable_notification))
        response = json.loads(response)
        return response

    def get_message(self):
        response = self._send_request("getUpdates")
        response = json.loads(response)
        return response


class EventWatcherEvent():
    def __init__(self, event_name, event_type, start_datetime, end_datetime, has_spawnpoints, has_quests, has_pokemon, bonus_lure_duration = None):
        self.name = event_name
        self.etype = event_type
        self.start = start_datetime
        self.end = end_datetime
        self.has_spawnpoints = has_spawnpoints
        self.has_quests = has_quests
        self.has_pokemon = has_pokemon
        self.bonus_lure_duration = bonus_lure_duration

    #TBD: remove testcode
    def __repr__(self):
        return f"name:{self.name} type:{self.etype} start:{self.start} end:{self.end} has_spawnpoints:{self.has_spawnpoints} has_quests:{self.has_quests} has_pokemon:{self.has_pokemon} bonus_lure_duration:{self.bonus_lure_duration}"

    @classmethod
    def fromPogoinfo(cls, raw_event):
        #check for valid input, unknown eventstart (=None) is accepted
        if raw_event["type"] is None or raw_event["end"] is None:
            return None

        # if event is added after eventstart to pogoinfo, start is Null
        bonus_lure_duration = None
        has_pokemon = False  
        event_type = raw_event["type"]

        # convert times to datetimes (pogoinfo provide local times)
        # handle unknown eventstart
        if raw_event["start"] is not None:
            start = datetime.strptime(raw_event["start"], "%Y-%m-%d %H:%M")
        else:
            start = None
        end = datetime.strptime(raw_event["end"], "%Y-%m-%d %H:%M")
        if end is None:
            return None

        # get bonus lure duration time
        bonus_lure_duration = None
        for bonus in raw_event["bonuses"]:
            if bonus.get("template", "") == "longer-lure":
                # if lure duration is not avaiable: use default 3 hours
                lure_duration_in_hour =  bonus.get("value", 3)
                bonus_lure_duration = lure_duration_in_hour*60
                break

        # check for changed pokemon spawn pool
        if raw_event["type"] == 'spotlight-hour' or raw_event["type"] == 'community-day' or raw_event["spawns"]:
            has_pokemon = True

        return cls(raw_event["name"], event_type, start, end, raw_event["has_spawnpoints"], raw_event["has_quests"], has_pokemon, bonus_lure_duration)     

    def get_duration_in_days(self):
        start = self.start
        #handle unknown start
        if self.start is None:
            start = datetime.now()
        return (self.end - start).total_seconds() / (3600 * 24)

    def check_event_start(self, timewindow_start, timewindow_end):
        #handle unknown start
        if self.start is None:
            return False
        if timewindow_start < self.start <= timewindow_end:
            return True
        else:
            return False

    def check_event_end(self, timewindow_start, timewindow_end):
        if timewindow_start < self.end <= timewindow_end:
            return True
        else:
            return False


class EventWatcher(mapadroid.utils.pluginBase.Plugin):
    def __init__(self, mad):
        super().__init__(mad)
        self._rootdir = os.path.dirname(os.path.abspath(__file__))
        self._mad = mad
        self._pluginconfig.read(self._rootdir + "/plugin.ini")
        self.type_to_name = {
            "community-day": "Community Days",
            "spotlight-hour": "Spotlight Hours",
            "event": "Regular Events",
            "default": "DEFAULT",
            "?": "Others"
        }
        self._last_pokemon_reset_check = datetime.now()
        self._last_quest_reset_check = datetime.now()
        # add plugin links/pages in madmin only, if plugin is activated by plugin.ini
        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
            self._versionconfig.read(self._rootdir + "/version.mpl")
            self.author = self._versionconfig.get("plugin", "author", fallback="ccev")
            self.url = self._versionconfig.get("plugin", "url", fallback="https://github.com/ccev/mp-eventwatcher")
            self.description = self._versionconfig.get(
                "plugin", "description", fallback="Automatically put Events that boost Spawns in your database")
            self.version = self._versionconfig.get("plugin", "version", fallback="1.0")
            self.pluginname = self._versionconfig.get("plugin", "pluginname", fallback="EventWatcher")
            self.templatepath = self._rootdir + "/template/"
            self.staticpath = self._rootdir + "/static/"
            self._routes = [
                ("/ew_event_list", self.pluginpage_event_list),
                ("/ew_about", self.pluginpage_about)
            ]
            self._hotlink = [
                ("Event list", "/ew_event_list", "List current events known by plugin"),
                ("About", "/ew_about", "Plugin information and credits")
            ]
            # register plugin incl. plugin subpages in madmin
            self._plugin = Blueprint(
                str(self.pluginname), __name__, static_folder=self.staticpath, template_folder=self.templatepath)
            for route, view_func in self._routes:
                self._plugin.add_url_rule(route, route.replace("/", ""), view_func=view_func)
            for name, link, description in self._hotlink:
                self._mad['madmin'].add_plugin_hotlink(name, self._plugin.name+"."+link.replace("/", ""),
                                                       self.pluginname, self.description, self.author, self.url,
                                                       description, self.version)

    def perform_operation(self):
        """The actual implementation of the identity plugin is to just return the
        argument
        """

        # do not change this part ▽▽▽▽▽▽▽▽▽▽▽▽▽▽▽
        if not self._pluginconfig.getboolean("plugin", "active", fallback=False):
            return False
        self._mad['madmin'].register_plugin(self._plugin)
        # do not change this part △△△△△△△△△△△△△△△

        # dont start plugin in config mode
        if self._mad['args'].config_mode:
            return False

        try:
            self.tz_offset = round((datetime.now() - datetime.utcnow()).total_seconds() / 3600)
            self._load_config_parameter()
            self.autoeventThread()
        except Exception as e:
            self._mad['logger'].error("Exception initializing EventWatcher: ")
            self._mad['logger'].exception(e)
            return False

        return True

    def _load_config_parameter(self):
        # General configuration parameter
        self.__sleep = self._pluginconfig.getint("plugin", "sleep", fallback=3600)
        self.__sleep_mainloop_in_s = 60
        self.__delete_events = self._pluginconfig.getboolean("plugin", "delete_events", fallback=False)
        self.__ignore_events_duration_in_days = self._pluginconfig.getint("plugin", "max_event_duration", fallback=999)
        # pokemon reset configuration parameter
        self.__reset_pokemon_enable = self._pluginconfig.getboolean("plugin", "reset_pokemon_enable", fallback=False)
        self.__reset_pokemon_truncate = self._pluginconfig.getboolean("plugin", "reset_pokemon_truncate", fallback=False)
        self.__reset_pokemon_restart_app = self._pluginconfig.getboolean("plugin", "reset_pokemon_restart_app", fallback=False)
        # quest reset configuration parameter
        self.__reset_quests_enable = self._pluginconfig.getboolean("plugin", "reset_quests_enable", fallback=False)
        reset_for = self._pluginconfig.get("plugin", "reset_quests_event_type", fallback="event")
        self.__quests_reset_types = {}
        for etype in reset_for.split(" "):
            etype = etype.strip()
            if ":" in etype:
                split = etype.split(":")
                etype = split[0]
                if "start" in split[1]:
                    times = ["start"]
                elif "end" in split[1]:
                    times = ["end"]
                else:
                    times = ["start", "end"]
            else:
                times = ["start", "end"]
            self.__quests_reset_types[etype] = times
        # Telegram info configuration parameter
        self.__tg_info_enable = self._pluginconfig.getboolean("plugin", "tg_info_enable", fallback=False)
        if self.__tg_info_enable:
            #Just read and check all the other TG related parameter, if function is enabled
            self._mad['logger'].info(f"EventWatcher: TG info feature activated")
            self.__token = self._pluginconfig.get("plugin", "tg_bot_token", fallback=None)
            self.__tg_chat_id = self._pluginconfig.get("plugin", "tg_chat_id", fallback=None)
            if self.__token is None or self.__tg_chat_id is None:
                self._mad['logger'].error(f"EventWatcher: TG options not set fully set in plugin.ini: 'tg_bot_token':{self.__token} 'tg_chat_id':{self.__tg_chat_id}")
                return False
            self.__tg_str_questreset_before_scan = self._pluginconfig.get("plugin", "tg_str_questreset_before_scan", fallback="Quests will be scanned in regular quest scan time window.")
            self.__tg_str_questreset_during_scan = self._pluginconfig.get("plugin", "tg_str_questreset_during_scan", fallback="Quests will be rescanned now.")
            self.__tg_str_questreset_after_scan = self._pluginconfig.get("plugin", "tg_str_questreset_after_scan", fallback="No quest rescan.")
            quest_timewindow_str=self._pluginconfig.get("plugin", "quest_rescan_timewindow")
            status, timewindow_list = self._get_timewindow_from_string(quest_timewindow_str)
            if status is False:
                self._mad['logger'].error(f"EventWatcher: Error while read parameter 'quest_rescan_timewindow' from plugin.ini. Please check value and pattern: quest_rescan_timewindow = ##-##")
                return False
            self.__quest_timewindow_start_h = timewindow_list[0]
            self.__quest_timewindow_end_h = timewindow_list[1]
        # Discord info configuration parameter
        self.__dc_info_enable = self._pluginconfig.getboolean("plugin", "dc_info_enable", fallback=False)
        if self.__dc_info_enable:
            self._mad['logger'].info(f"EventWatcher: Discord info feature activated")
            self.__dc_webhook_url = self._pluginconfig.get("plugin", "dc_webhook_url", fallback=None)
            self.__dc_webook_username = self._pluginconfig.get("plugin", "dc_webhook_username", fallback="PoGo Event Bot")
            self.__dc_webhook_embedTitle = self._pluginconfig.get("plugin", "dc_webhook_embedTitle", fallback="Event Quest notification")
            
            if self.__dc_webhook_url is None:
                self._mad['logger'].error(f"EventWatcher: Discord Webhook 'Url':{self.__dc_webhook_url} not configured in plugin.ini")
                return False

    def _get_timewindow_from_string(self, timewindow_str):
        try:
            timewindow_list = []
            timewindow_str_list = timewindow_str.split('-')
            if len(timewindow_str_list) == 2:
                timewindow_list.append(int(timewindow_str_list[0]))
                timewindow_list.append(int(timewindow_str_list[1]))
                return True, timewindow_list
            else:
                return False, timewindow_list
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error in _get_timewindow_from_string()")
            self._mad['logger'].exception(e)
            return False, timewindow_list

    def _convert_time(self, time_string, local=True):
        if time_string is None:
            return None
        time = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
        if not local:
            time = time + timedelta(hours=self.tz_offset)
        return time

    def _send_dc_info_questreset(self, event_name, event_change_str):
        if self.__dc_info_enable:
            embedUsername = self.__dc_webook_username
            data = {
                "content" : "",
                "username" : embedUsername
            }
            url=self.__dc_webhook_url
            embedDescription = f"Quests have been deleted because: {event_change_str} for Event {event_name}"
            embedTitle = self.__dc_webhook_embedTitle

            data["embeds"] = [
            {
                "description" : embedDescription,
                "title" : embedTitle
            }
            ]

            result = requests.post(url, json = data)

            try:
                result.raise_for_status()
            except requests.exceptions.HTTPError as err:
                self._mad['logger'].error(f"EventWatcher: unable to sent Discord info message: result:{result.status_code}")
            else:
                self._mad['logger'].success(f"EventWatcher: send Discord info message:{embedDescription} result:{result.status_code}")
 

    def _send_tg_info_questreset(self, event_name, event_change_str):
        if self.__tg_info_enable:
            now = datetime.now()
            first_rescan_time = now.replace(hour=self.__quest_timewindow_start_h, minute=0)
            latest_rescan_time = now.replace(hour=self.__quest_timewindow_end_h, minute=0)
            if now < first_rescan_time:     # quest changed before regular quest scan
                rescan_str = self.__tg_str_questreset_before_scan
            elif now < latest_rescan_time:  # quest changed after regular quest scan
                rescan_str = self.__tg_str_questreset_during_scan
            else:                           # quest changed outside quest scan time window
                rescan_str = self.__tg_str_questreset_after_scan
            #@TODO: make quest reset string configurable
            info_msg = f"\U000026A0 Info: Quests gelöscht aufgrund {event_change_str} von Event {event_name}. {rescan_str}"
            result = self._api.send_message(self.__tg_chat_id, info_msg)
            if result["ok"]:
                self._mad['logger'].success(f"EventWatcher: send Telegram info message:{info_msg} result:{result}")
            else:
                self._mad['logger'].error(f"EventWatcher: send Telegram info message failed with result:{result}")


    def _reset_all_quests(self):
        sql_query = "TRUNCATE trs_quest"
        dbreturn = self._mad['db_wrapper'].execute(sql_query, commit=True)
        self._mad['logger'].info(f'EventWatcher: quests deleted by SQL query: {sql_query} return: {dbreturn}')

    def _restart_pogo_app(self, origin_name):
        self._mad['logger'].info(f"EventWatcher: restart PoGo app on device '{origin_name}' ...")
        temp_comm = self._mad['ws_server'].get_origin_communicator(origin_name)
        result = temp_comm.restart_app("com.nianticlabs.pokemongo")
        if result is True:
            self._mad['logger'].success(f"EventWatcher: restart PoGo app on device '{origin_name}' successful")
        else:
            self._mad['logger'].error(f"EventWatcher: restart PoGo app on device '{origin_name}' failed with result:{result}")

    def _reset_pokemon(self, eventchange_datetime_UTC):
        if self.__reset_pokemon_truncate:
            sql_query = "TRUNCATE pokemon"
            sql_args = None
        else:
            # SQL query: delete mon
            eventchange_timestamp = eventchange_datetime_UTC.strftime("%Y-%m-%d %H:%M:%S")
            sql_query = "DELETE FROM pokemon WHERE last_modified < %s AND disappear_time > %s"
            sql_args = (
                eventchange_timestamp,
                eventchange_timestamp
            )
        dbreturn = self._mad['db_wrapper'].execute(sql_query, args=sql_args, commit=True)
        self._mad['logger'].info(f'EventWatcher: pokemon deleted by SQL query: {sql_query} arguments: {sql_args} return: {dbreturn}')

        #restart pokemon go apps on all devices
        if self.__reset_pokemon_restart_app:
            origin_list = self._mad['ws_server'].get_reg_origins()
            for origin in origin_list:
                self._restart_pogo_app(origin)

    def _check_pokemon_resets(self):
        self._mad['logger'].info("EventWatcher: check pokemon changing events")
        try:
            #get current time to check for event start and event end
            now = datetime.now()

            # check, if one of the pokemon event is just started or ended
            for event in self._pokemon_events:
                # event start during last check?
                if event.check_event_start(self._last_pokemon_reset_check, now):
                    self._mad['logger'].success(f'EventWatcher: event start detected for event {event.name} ({event.etype}) -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event start and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event.start - timedelta(hours=self.tz_offset))
                    break
                # event end during last check?
                if event.check_event_end(self._last_pokemon_reset_check, now):
                    self._mad['logger'].success(f'EventWatcher: event end detected for event {event.name} ({event.etype}) -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event end and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event.end - timedelta(hours=self.tz_offset))
                    break
            self._last_pokemon_reset_check = now
        except Exception as e:
                    self._mad['logger'].error(f"EventWatcher: Error while checking Pokemon Resets")
                    self._mad['logger'].exception(e)

    def _check_quest_resets(self):
        self._mad['logger'].info("EventWatcher: check quest changing events")
        try:
            #get current time to check for event start and event end
            now = datetime.now()

            # check, if one of the pokemon event is just started or ended
            for event in self._quest_events:
                # event starts during last check?
                if "start" in self.__quests_reset_types.get(event.etype, []):
                    if event.check_event_start(self._last_quest_reset_check, now):
                        self._mad['logger'].success(f'EventWatcher: event start detected for event {event.name} ({event.etype}) -> reset quests')
                        # remove all quests from MAD DB
                        self._reset_all_quests()
                        self._mad["mapping_manager"].update()
                        self._send_tg_info_questreset(event.name, "Start")
                        self._send_dc_info_questreset(event.name, "Start")
                        break
                # event end during last check?
                if "end" in self.__quests_reset_types.get(event.etype, []):
                    if event.check_event_end(self._last_quest_reset_check, now):
                        self._mad['logger'].success(f'EventWatcher: event end detected for event {event.name} ({event.etype}) -> reset quests')
                        # remove all quests from MAD DB
                        self._reset_all_quests()
                        self._mad["mapping_manager"].update()
                        self._send_tg_info_questreset(event.name, "Ende")
                        self._send_dc_info_questreset(event.name, "Ende")
                        break
            self._last_quest_reset_check = now
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error while checking Quest Resets")
            self._mad['logger'].exception(e)

    def _update_spawn_events_in_mad_db(self):
        # abort, if there is no spawn event in list -> nothing to do
        if len(self._spawn_events) == 0:
            self._mad['logger'].info("EventWatcher: no spawnpoint changing events -> no event update in MAD-DB needed")
            return

        self._mad['logger'].info("EventWatcher: Check spawnpoint changing events")
        try:
            # get existing events from the db and bring them in a format that's easier to work with
            query = "select event_name, event_start, event_end from trs_event;"
            db_events = self._mad['db_wrapper'].autofetch_all(query)
            events_in_db = {}
            for db_event in db_events:
                events_in_db[db_event["event_name"]] = {
                    "event_start": db_event["event_start"],
                    "event_end": db_event["event_end"]
                }

            # check if there are missing event entries in the db and if so, create them
            for event_type_name in self.type_to_name.values():
                if event_type_name not in events_in_db.keys():
                    vals = {
                        "event_name": event_type_name,
                        "event_start": self.DEFAULT_TIME,
                        "event_end": self.DEFAULT_TIME,
                        "event_lure_duration": DEFAULT_LURE_DURATION
                    }
                    self._mad['db_wrapper'].autoexec_insert("trs_event", vals)
                    self._mad['logger'].success(f"EventWatcher: Created event type {event_type_name}")

                    events_in_db[event_type_name] = {
                        "event_start": self.DEFAULT_TIME,
                        "event_end": self.DEFAULT_TIME
                    }

            # go through all events that boost spawns, check if their times differ from the event in the db
            # and if so, update the db accordingly
            updated_mad_events = []
            for event in self._spawn_events:
                if event.etype not in updated_mad_events:
                    type_name = self.type_to_name.get(event.etype, "Others")
                    db_entry = events_in_db[type_name]
                    #handle unknown eventstart
                    if event.start is None:
                        continue
                    if db_entry["event_start"] != event.start or db_entry["event_end"] != event.end:
                        vals = {
                            "event_start": event.start.strftime('%Y-%m-%d %H:%M:%S'),
                            "event_end": event.end.strftime('%Y-%m-%d %H:%M:%S'),
                            "event_lure_duration": event.bonus_lure_duration if event.bonus_lure_duration is not None else DEFAULT_LURE_DURATION
                        }
                        where = {
                            "event_name": self.type_to_name.get(event.etype, "Others")
                        }
                        self._mad['db_wrapper'].autoexec_update("trs_event", vals, where_keyvals=where)
                        self._mad['logger'].success(f'EventWatcher: Updated MAD event {event.etype} with start:{vals["event_start"]}, end:{vals["event_end"]}, lure_duration:{vals["event_lure_duration"]}')

                    updated_mad_events.append(event.etype)

            # just deletes all events that aren't part of Event Watcher
            if self.__delete_events:
                for db_event_name in events_in_db:
                    if not db_event_name in self.type_to_name.values():
                        vals = {
                            "event_name": db_event_name
                        }
                        self._mad['db_wrapper'].autoexec_delete("trs_event", vals)
                        self._mad['logger'].success(f"EventWatcher: Deleted event {db_event_name}")
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error while checking Spawn Events: {e}")

    def _get_events(self):
        self._mad['logger'].info("EventWatcher: Update event list from external")
        try:
            # get the event list from github
            raw_events = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/v2/active/events.json").json()
            #raw_events = requests.get("https://raw.githubusercontent.com/acocalypso/mp-eventwatcher/v2refactor/tests/events.json").json()
            self._all_events = []
            self._spawn_events = []
            self._quest_events = []
            self._pokemon_events = []

            # sort out events that have ended, bring them into a format that's easier to work with
            # and put them into seperate lists depending if they boost spawns or reset quests
            # then sort those after their start time
            for raw_event in raw_events:
                new_event = EventWatcherEvent.fromPogoinfo(raw_event)
                # sort out invalid or outdated events
                if new_event is None:
                    continue
                if new_event.end < datetime.now():
                    continue
                # season workaround: ignore events with long duration
                if new_event.get_duration_in_days() > self.__ignore_events_duration_in_days:
                    self._mad['logger'].info(f'EventWatcher: Ignore following event because duration exceed configurated limit of {self.__ignore_events_duration_in_days} days: {raw_event["name"]}')
                    continue
                # store valid events
                self._all_events.append(new_event)
                # get events with changed spawnpoints
                # TBD: check how to handle events with just bonus_lure_duration. Hint: MAD ignores lure_duration setting for event 'DEFAULT' (see function _extract_args_single_stop)
                if new_event.has_spawnpoints:
                    self._spawn_events.append(new_event)
                # get events with changed quests
                if new_event.has_quests:
                    self._quest_events.append(new_event)
                # get events which has changed pokemon pool
                if new_event.has_pokemon:
                    self._pokemon_events.append(new_event)

            #sort pokemon lists
            self._quest_events = sorted(self._quest_events, key=lambda e: (e.start is None, e.start))
            self._spawn_events = sorted(self._spawn_events, key=lambda e: (e.start is None, e.start))
            self._pokemon_events = sorted(self._pokemon_events, key=lambda e: (e.start is None, e.start))
            self._all_events = sorted(self._pokemon_events, key=lambda e: (e.start is None, e.start))
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error while getting events: {e}")

    def EventWatcher(self):
        last_checked_events = datetime(2000, 1, 1, 0, 0, 0)
        if(self.__tg_info_enable):
            self._api = SimpleTelegramApi(self.__token)

        # load events initally
        self._get_events()
        self._update_spawn_events_in_mad_db()
        last_checked_events = datetime.now()

        while True:
            #if enabled, run pokemon reset check every cycle to ensure pokemon rescan just after spawn event change
            if self.__reset_pokemon_enable:
                self._check_pokemon_resets()

            #if enabled, run quest reset check every cycle to ensure quest rescan just after quest event change
            if self.__reset_quests_enable:
                self._check_quest_resets()

            # check for new events on event website only with configurated event check time
            # check after reset actions to avoid removing events before event end is detected.
            if (datetime.now() - last_checked_events) >= timedelta(seconds=self.__sleep):
                self._get_events()
                if len(self._spawn_events) > 0:
                    self._update_spawn_events_in_mad_db()
                last_checked_events = datetime.now()

            # wait mainloop time
            time.sleep(self.__sleep_mainloop_in_s)

    def autoeventThread(self):
        self._mad['logger'].info("Starting Event Watcher")

        ae_worker = Thread(name="EventWatcher", target=self.EventWatcher)
        ae_worker.daemon = True
        ae_worker.start()

    @auth_required
    def pluginpage_event_list(self):
        try:
            event_list = self._all_events
            generated_html = render_template("eventwatcher.html", header="EventWatcher", title="Event list", event_list=event_list)
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error while generating pluginpage 'Event list'")
            self._mad['logger'].exception(e)
        return generated_html

    @auth_required
    def pluginpage_about(self):
        try:
            generated_html = render_template("about.html", header="EventWatcher", title="About")
        except Exception as e:
            self._mad['logger'].error(f"EventWatcher: Error while generating pluginpage 'About'")
            self._mad['logger'].exception(e)
        return generated_html