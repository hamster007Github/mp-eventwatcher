import os
import requests
import json
import time
import re

from threading import Thread
from flask import render_template, Blueprint, jsonify
from datetime import datetime, timedelta

from mapadroid.madmin.functions import auth_required
import mapadroid.utils.pluginBase

DEFAULT_LURE_DURATION = 30
DEFAULT_TIME = datetime(2030, 1, 1, 0, 0, 0)

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
        #check for valid input:
        if raw_event["type"] is None or raw_event["start"] is None or raw_event["end"] is None:
            return None   

        bonus_lure_duration = None
        has_pokemon = False  
        event_type = raw_event["type"]
        
        # convert times to datetimes (pogoinfo provide local times)
        start = datetime.strptime(raw_event["start"], "%Y-%m-%d %H:%M")
        end = datetime.strptime(raw_event["end"], "%Y-%m-%d %H:%M")
        if start is None or end is None:
            return None

        # get bonus lure duration time
        bonus_lure_duration = None
        for bonus in raw_event["bonuses"]:
            if bonus.get("template", "") == "longer-lure":
                bonus_lure_duration = bonus["value"]*60
                break
                
        # check for changed pokemon spawn pool
        if raw_event["type"] == 'spotlight-hour' or raw_event["type"] == 'community-day' or raw_event["spawns"]:
            has_pokemon = True
                
        return cls(raw_event["name"], event_type, start, end, raw_event["has_spawnpoints"], raw_event["has_quests"], has_pokemon, bonus_lure_duration)     

    def get_duration_in_days(self):
        return (self.end - self.start).total_seconds() / (3600 * 24)

    def check_event_start(self, time_datetime, timewindow_seconds):
        if self.start <= time_datetime <= (self.start + timedelta(seconds=timewindow_seconds)):
            return True
        else:
            return False

    def check_event_end(self, time_datetime, timewindow_seconds):
        if self.end <= time_datetime <= (self.end + timedelta(seconds=timewindow_seconds)):
            return True
        else:
            return False


class EventWatcher(mapadroid.utils.pluginBase.Plugin):
    def __init__(self, mad):
        super().__init__(mad)
        
        self._rootdir = os.path.dirname(os.path.abspath(__file__))
        
        self._mad = mad
        
        self._pluginconfig.read(self._rootdir + "/plugin.ini")
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
            ("About", "/ew_about", "Plugin information and credits"),
        ]
        
        self.type_to_name = {
            "community-day": "Community Days",
            "spotlight-hour": "Spotlight Hours",
            "event": "Regular Events",
            "default": "DEFAULT",
            "?": "Others"
        }
        self._last_pokemon_reset_date = datetime(2000, 1, 1, 0, 0, 0)
        self._last_quest_reset_date = datetime(2000, 1, 1, 0, 0, 0)

        if self._pluginconfig.getboolean("plugin", "active", fallback=False):
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
            self.__sleep = self._pluginconfig.getint("plugin", "sleep", fallback=3600)
            self.__sleep_mainloop_in_s = 60
            self.__delete_events = self._pluginconfig.getboolean("plugin", "delete_events", fallback=False)
            self.__ignore_events_duration_in_days = self._pluginconfig.getint("plugin", "max_event_duration", fallback=999)
            self.__reset_cooldown_in_s = 1800 # minimum cooldown time between 2 pokemon/quest resets. 30 minutes
            
            # pokemon reset configuration
            self.__reset_pokemon_enable = self._pluginconfig.getboolean("plugin", "reset_pokemon_enable", fallback=False)
            self.__reset_pokemon_truncate = self._pluginconfig.getboolean("plugin", "reset_pokemon_truncate", fallback=False)
            
            # quest reset configuration
            self.__quests_enable = self._pluginconfig.getboolean("plugin", "reset_quests_enable", fallback=False)
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
            
            self.autoeventThread()

        except Exception as e:
            self._mad['logger'].error("Exception initializing EventWatcher: ")
            self._mad['logger'].exception(e)
            return False

        return True

    def _convert_time(self, time_string, local=True):
        if time_string is None:
            return None
        time = datetime.strptime(time_string, "%Y-%m-%d %H:%M")
        if not local:
            time = time + timedelta(hours=self.tz_offset)
        return time

    def _reset_all_quests(self):
        sql_query = "TRUNCATE trs_quest"
        dbreturn = self._mad['db_wrapper'].execute(sql_query, commit=True)
        self._mad['logger'].info(f'EventWatcher: quests deleted by SQL query: {sql_query} return: {dbreturn}')    
    
    def _reset_pokemon(self, eventchange_datetime_UTC):
        if self.__reset_pokemon_truncate:
            sql_query = "TRUNCATE pokemon"
            sql_args = None
        else:
            sql_query = "DELETE FROM pokemon WHERE last_modified < %s AND disappear_time > %s"
            datestring = eventchange_datetime_UTC.strftime("%Y-%m-%d %H:%M:%S")
            sql_args = (
                datestring,
                datestring
            )
        dbreturn = self._mad['db_wrapper'].execute(sql_query, args=sql_args, commit=True)
        self._mad['logger'].info(f'EventWatcher: pokemon deleted by SQL query: {sql_query} arguments: {sql_args} return: {dbreturn}')

    def _check_pokemon_resets(self):
        if self._pokemon_events:
            #get current time to check for event start and event end
            now = datetime.now()
            
            #cooldown check (only check for event start / end, if last pokemon reset is > __reset_cooldown_in_s)
            if (self._last_pokemon_reset_date + timedelta(seconds=self.__reset_cooldown_in_s)) > now:
                self._mad['logger'].info(f"EventWatcher: no check of pokemon changing events, because of cooldown (last reset:{self._last_pokemon_reset_date})")
                return
            self._mad['logger'].info("EventWatcher: check pokemon changing events")
            # check, if one of the pokemon event is just started or ended
            for event in self._pokemon_events:
                # event start during last 2 mainloop cycles?
                if event.check_event_start(now, 2*self.__sleep_mainloop_in_s):
                    self._mad['logger'].info(f'EventWatcher: event start detected for event {event.name} ({event.etype}) -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event start and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event.start - timedelta(hours=self.tz_offset))
                    self._last_pokemon_reset_date = now
                    return
                # event end during last 2 mainloop cycles?
                if event.check_event_end(now, 2*self.__sleep_mainloop_in_s):
                    self._mad['logger'].info(f'EventWatcher: event end detected for event {event.name} ({event.etype}) -> reset pokemon')
                    # remove pokemon from MAD DB, which are scanned before event end and needs to be rescanned, adapt time from local to UTC time
                    self._reset_pokemon(event.end - timedelta(hours=self.tz_offset))
                    self._last_pokemon_reset_date = now
                    return

    def _check_quest_resets(self):
        if self._quest_events:
            #get current time to check for event start and event end
            now = datetime.now()   
        
            #cooldown check (only check for event start / end, if last quest reset is > __reset_cooldown_in_s)
            if (self._last_quest_reset_date + timedelta(seconds=self.__reset_cooldown_in_s)) > now:
                self._mad['logger'].info(f"EventWatcher: no check of quest changing events, because of cooldown (last reset:{self._last_quest_reset_date})")
                return
            
            self._mad['logger'].info("EventWatcher: check quest changing events")
            # check, if one of the pokemon event is just started or ended
            for event in self._quest_events:
                # event starts/end during last 2 mainloop cycles?
                if "start" in self.__quests_reset_types.get(event.etype, []):
                    if event.check_event_start(now, 2*self.__sleep_mainloop_in_s):
                        self._mad['logger'].info(f'EventWatcher: event start detected for event {event.name} ({event.etype}) -> reset quests')
                        # remove all quests from MAD DB
                        self._reset_all_quests()
                        self._mad["mapping_manager"].update()
                        self._last_quest_reset_date = now
                        return
                if "end" in self.__quests_reset_types.get(event.etype, []):
                    if event.check_event_end(now, 2*self.__sleep_mainloop_in_s):
                        self._mad['logger'].info(f'EventWatcher: event end detected for event {event.name} ({event.etype}) -> reset quests')
                        # remove all quests from MAD DB
                        self._reset_all_quests()
                        self._mad["mapping_manager"].update()
                        self._last_quest_reset_date = now
                        return

    def _check_spawn_events(self):
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
                    self._mad['logger'].success(f"EventWatcher: Updated MAD event {event.etype} with start:{event.start}, end:{event.end}, lure_duration:{event.event_lure_duration}")

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

    def _get_events(self):
        # get the event list from github
        raw_events = requests.get("https://raw.githubusercontent.com/ccev/pogoinfo/v2/active/events.json").json()
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
        self._quest_events = sorted(self._quest_events, key=lambda e: e.start)
        self._spawn_events = sorted(self._spawn_events, key=lambda e: e.start)
        self._pokemon_events = sorted(self._pokemon_events, key=lambda e: e.start)
        self._all_events = sorted(self._pokemon_events, key=lambda e: e.start)

    def EventWatcher(self):
        last_checked_events = datetime(2000, 1, 1, 0, 0, 0)
        #newEvent = EventWatcherEvent("Testname", 'community-day', datetime.now(), datetime.now())
        
        while True:
            # check for new events on event website only with configurated event check time
            if (datetime.now() - last_checked_events) >= timedelta(seconds=self.__sleep):
                try:
                    self._get_events()
                except Exception as e:
                    self._mad['logger'].error(f"EventWatcher: Error while getting events: {e}")

                if len(self._spawn_events) > 0:
                    self._mad['logger'].info("EventWatcher: Check Spawnpoint changing Events")
                    try:
                        self._check_spawn_events()
                    except Exception as e:
                        self._mad['logger'].error(f"EventWatcher: Error while checking Spawn Events: {e}")

                last_checked_events = datetime.now()
            
            #if enabled, run pokemon reset check every cycle to ensure pokemon rescan just after spawn event change
            if self.__reset_pokemon_enable:
                try:
                    self._check_pokemon_resets()
                except Exception as e:
                    self._mad['logger'].error(f"EventWatcher: Error while checking Pokemon Resets")
                    self._mad['logger'].exception(e)

            #if enabled, run quest reset check every cycle to ensure quest rescan just after quest event change
            if self.__quests_enable:
                try:
                    self._check_quest_resets()
                except Exception as e:
                    self._mad['logger'].error(f"EventWatcher: Error while checking Quest Resets")
                    self._mad['logger'].exception(e)
                
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