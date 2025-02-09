# runner.py
#
# Copyright 2020 brombinmirko <send@mirko.pm>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os, subprocess, urllib.request, json, tarfile, time, shutil, re, hashlib

from glob import glob
from threading import Thread
from pathlib import Path
from datetime import date

from .download import BottlesDownloadEntry
from .pages.list import BottlesListEntry
from .utils import UtilsTerminal, UtilsLogger

logging = UtilsLogger()

class RunAsync(Thread):

    def __init__(self, task_name, task_func, task_args=False):
        Thread.__init__(self)

        self.task_name = task_name
        self.task_func = task_func
        self.task_args = task_args

    def run(self):
        logging.debug('Running async job `%s`.' % self.task_name)

        if not self.task_args:
            self.task_func()
        else:
            self.task_func(self.task_args)

class BottlesRunner:

    '''
    Define repositories URLs
    TODO: search for vanilla wine binary repository
    '''
    repository = "https://github.com/lutris/wine/releases"
    repository_api = "https://api.github.com/repos/lutris/wine/releases"
    proton_repository = "https://github.com/GloriousEggroll/proton-ge-custom/releases"
    proton_repository_api = "https://api.github.com/repos/GloriousEggroll/proton-ge-custom/releases"
    dxvk_repository = "https://github.com/doitsujin/dxvk/releases"
    dxvk_repository_api = "https://api.github.com/repos/doitsujin/dxvk/releases"
    dependencies_repository = "https://raw.githubusercontent.com/bottlesdevs/dependencies/main/"
    dependencies_repository_index = "%s/index.json" % dependencies_repository

    '''
    Define local path for temp and runners
    '''
    temp_path = "%s/.local/share/bottles/temp" % Path.home()
    runners_path = "%s/.local/share/bottles/runners" % Path.home()
    bottles_path = "%s/.local/share/bottles/bottles" % Path.home()
    dxvk_path = "%s/.local/share/bottles/dxvk" % Path.home()

    '''
    Do not implement dxgi.dll <https://github.com/doitsujin/dxvk/wiki/DXGI>
    '''
    dxvk_dlls = [
        "d3d10core.dll",
        "d3d11.dll",
        "d3d9.dll",
    ]

    runners_available = []
    dxvk_available = []
    local_bottles = {}

    '''
    Structure of bottle configuration file
    '''
    sample_configuration = {
        "Name": "",
        "Runner": "",
        "Path": "",
        "Custom_Path": False,
        "Environment": "",
        "Creation_Date": "",
        "Update_Date": "",
        "Parameters": {
            "dxvk": False,
            "dxvk_hud": False,
            "esync": False,
            "fsync": False,
            "aco_compiler": False,
            "discrete_gpu": False,
            "virtual_desktop": False,
            "virtual_desktop_res": "1280x720",
            "pulseaudio_latency": False,
            "environment_variables": "",
            "dll_overrides": ""
        },
        "Installed_Dependencies" : [],
        "Programs" : {}
    }

    environments = {
        "gaming": {
            "Runner": "wine",
            "Parameters": {
                "dxvk": True,
                "esync": True,
                "discrete_gpu": True,
                "pulseaudio_latency": True
            }
        },
        "software": {
            "Runner": "wine",
            "Parameters": {
                "dxvk": True
            }
        }
    }

    supported_dependencies = {}

    def __init__(self, window, **kwargs):
        super().__init__(**kwargs)

        '''
        Common variables
        '''
        self.window = window
        self.settings = window.settings
        self.utils_conn = window.utils_conn

        self.check_runners(install_latest=False)
        self.check_dxvk(install_latest=False)
        self.fetch_dependencies()
        self.check_bottles()
        self.clear_temp()

    '''
    Performs all checks in one async shot
    '''
    def async_checks(self):
        self.check_runners_dir()
        self.check_runners()
        self.check_dxvk()
        self.check_bottles()
        self.fetch_dependencies()

    def checks(self):
        a = RunAsync('checks', self.async_checks);a.start()

    '''
    Clear temp path
    '''
    def clear_temp(self, force=False):
        logging.info("Cleaning the temp path.")

        if self.settings.get_boolean("temp") or force:
            for f in os.listdir(self.temp_path):
                os.remove(os.path.join(self.temp_path, f))


    '''
    Check if standard directories not exists, then create
    '''
    def check_runners_dir(self):
        try:
            if not os.path.isdir(self.runners_path):
                logging.info("Runners path doens't exist, creating now.")
                os.makedirs(self.runners_path, exist_ok=True)

            if not os.path.isdir(self.bottles_path):
                logging.info("Bottles path doens't exist, creating now.")
                os.makedirs(self.bottles_path, exist_ok=True)

            if not os.path.isdir(self.dxvk_path):
                logging.info("Dxvk path doens't exist, creating now.")
                os.makedirs(self.dxvk_path, exist_ok=True)

            if not os.path.isdir(self.temp_path):
                logging.info("Temp path doens't exist, creating now.")
                os.makedirs(self.temp_path, exist_ok=True)
        except:
            logging.info("One or more path cannot be created.")
            return False

        return True

    '''
    Get latest runner updates
    '''
    def get_runner_updates(self):
        updates = {}

        if self.utils_conn.check_connection():
            '''
            wine
            '''
            with urllib.request.urlopen(self.repository_api) as url:
                releases = json.loads(url.read().decode())
                for release in [releases[0], releases[1], releases[2]]:
                    tag = release["tag_name"]
                    file = release["assets"][0]["name"]
                    if "%s-x86_64" % tag not in self.runners_available:
                        updates[tag] = file
                    else:
                        logging.warning("Latest wine runner is `%s` and is already installed." % tag)

            '''
            proton
            '''
            with urllib.request.urlopen(self.proton_repository_api) as url:
                releases = json.loads(url.read().decode())
                for release in [releases[0], releases[1], releases[2]]:
                    tag = release["tag_name"]
                    file = release["assets"][0]["name"]
                    if "Proton-%s" % tag not in self.runners_available:
                        updates[tag] = file
                    else:
                        logging.warning("Latest proton runner is `%s` and is already installed." % tag)

        '''
        Send a notificationif the user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            if len(updates) == 0:
                self.window.send_notification("Download manager",
                                              "No runner updates available.",
                                              "software-installed-symbolic")

        return updates

    '''
    Get latest dxvk updates
    '''
    def get_dxvk_updates(self):
        updates = {}

        if self.utils_conn.check_connection():
            with urllib.request.urlopen(self.dxvk_repository_api) as url:
                releases = json.loads(url.read().decode())
                for release in [releases[0], releases[1], releases[2]]:
                    tag = release["tag_name"]
                    file = release["assets"][0]["name"]
                    if "dxvk-%s" % tag[1:] not in self.dxvk_available:
                        updates[tag] = file
                    else:
                        logging.warning("Latest dxvk is `%s` and is already installed." % tag)

        '''
        Send a notificationif the user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            if len(updates) == 0:
                self.window.send_notification("Download manager",
                                              "No dxvk updates available.",
                                              "software-installed-symbolic")

        return updates

    '''
    Extract a component archive
    '''
    def extract_component(self, component, archive):
        if component in ["runner", "runner:proton"]: path = self.runners_path
        if component == "dxvk": path = self.dxvk_path

        archive = tarfile.open("%s/%s" % (self.temp_path, archive))
        archive.extractall(path)

    '''
    Download a specific component release
    '''
    def download_component(self, component, tag, file, rename=False, checksum=False):
        if component == "runner": repository = self.repository
        if component == "runner:proton": repository = self.proton_repository
        if component == "dxvk": repository = self.dxvk_repository
        if component == "dependency":
            repository = self.dependencies_repository
            download_url = tag
        else:
            download_url = "%s/download/%s/%s" % (repository, tag, file)

        '''
        Check if file already exists in temp path then do not
        download it again
        '''
        file = rename if rename else file
        if os.path.isfile("%s/%s" % (self.temp_path, file)):
            logging.warning("File `%s` already exists in temp, skipping." % file)
        else:
            urllib.request.urlretrieve(download_url, "%s/%s" % (self.temp_path, file))

        '''
        The `rename` parameter mean that downloaded file should be
        renamed to another name
        '''
        if rename:
            logging.info("Renaming `%s` to `%s`." % (file, rename))
            file_path = "%s/%s" % (self.temp_path, rename)
            os.rename("%s/%s" % (self.temp_path, file), file_path)
        else:
            file_path = "%s/%s" % (self.temp_path, file)

        '''
        Compare checksums to check file corruption
        '''
        if checksum:
            checksum = checksum.lower()

            local_checksum = hashlib.md5()

            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    local_checksum.update(chunk)

            local_checksum = local_checksum.hexdigest().lower()

            if local_checksum != checksum:
                logging.error("Downloaded file `%s` looks corrupted." % file)
                logging.error("Source checksum: `%s` downloaded: `%s`" % (
                    checksum, local_checksum))
                self.window.send_notification(
                    "Bottles",
                    "Downloaded file `%s` looks corrupted. Try again." % file,
                    "dialog-error-symbolic")

                os.remove(file_path)
                return False

        return True

    '''
    Localy install a new component (runner, dxvk, ..) async
    '''
    def async_install_component(self, args):
        component, tag, file = args

        '''
        Send a notification for download start if the
        user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            self.window.send_notification("Download manager",
                                          "Installing `%s` runner …" % tag,
                                          "document-save-symbolic")

        '''
        Add a new entry to the download manager
        '''
        if component == "runner": file_name = tag
        if component == "runner:proton": file_name = "proton-%s" % tag
        if component == "dxvk": file_name = "dxvk-%s" % tag

        download_entry = BottlesDownloadEntry(file_name=file_name, stoppable=False)
        self.window.box_downloads.add(download_entry)

        logging.info("Installing the `%s` component." % tag)

        '''
        Run the progressbar update async
        '''
        a = RunAsync('pulse', download_entry.pulse);a.start()

        '''
        Download and extract the component archive
        '''
        self.download_component(component, tag, file)
        self.extract_component(component, file)

        '''
        Clear available component list and do the check again
        '''
        if component in ["runner", "runner:proton"]:
            self.runners_available = []
            self.check_runners()

        if component == "dxvk":
            self.dxvk_available = []
            self.check_dxvk()

        '''
        Send a notification for download end if the
        user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            self.window.send_notification("Download manager",
                                          "Installation of `%s` component finished!" % tag,
                                          "software-installed-symbolic")
        '''
        Remove the entry from the download manager
        '''
        download_entry.destroy()

        '''
        Update components
        '''
        if component in ["runner", "runner:proton"]:
            self.window.page_preferences.update_runners()
        if component == "dxvk":
            self.window.page_preferences.update_dxvk()

    def install_component(self, component,  tag, file):
        if self.utils_conn.check_connection(True):
            a = RunAsync('install', self.async_install_component, [component,
                                                                   tag,
                                                                   file])
            a.start()

    '''
    Method for deoendency installations
    '''
    def async_install_dependency(self, args):
        configuration, dependency, widget = args

        '''
        Set UI to not usable
        '''
        self.window.set_usable_ui(False)

        '''
        Send a notification for download start if the
        user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            self.window.send_notification("Download manager",
                                          "Installing %s in %s bottle …" % (
                                              dependency[0],
                                              configuration.get("Name")
                                          ),
                                          "document-save-symbolic")

        '''
        Add a new entry to the download manager
        '''
        download_entry = BottlesDownloadEntry(dependency[0], stoppable=False)
        self.window.box_downloads.add(download_entry)

        logging.info("Installing the `%s` dependency for `%s` bottle." % (
            dependency[0], configuration.get("Name")
        ))

        '''
        Run the progressbar update async
        '''
        a = RunAsync('pulse', download_entry.pulse);a.start()

        '''
        Get dependency manifest from repository
        '''
        dependency_manifest = self.fetch_dependency_manifest(dependency[0])

        '''
        Execute installation steps
        '''
        for step in dependency_manifest.get("Steps"):
            print(step["action"])
            '''
            Step type: delete_sys32_dlls
            '''
            if step["action"] == "delete_sys32_dlls":
                for dll in step["dlls"]:
                    try:
                        logging.info("Removing `%s` dll from system32 for `%s` bottle" % (
                            dll, configuration.get("Name")
                        ))
                        os.remove("%s/%s/drive_c/windows/system32/%s" % (
                            self.bottles_path, configuration.get("Name"), dll))
                    except:
                        logging.error("`%s` dll not found for `%s` bottle, failed to remove from system32."% (
                            dll, configuration.get("Name")
                        ))
            '''
            Step type: install_exe, install_msi
            '''
            if step["action"] in ["install_exe", "install_msi"]:
                download = self.download_component("dependency",
                                        step.get("url"),
                                        step.get("file_name"),
                                        step.get("rename"),
                                        checksum=step.get("file_checksum"))
                if download:
                    if step.get("rename"):
                        file = step.get("rename")
                    else:
                        file = step.get("file_name")
                    self.run_executable(configuration, "%s/%s" % (
                        self.temp_path, file))
                else:
                    widget.btn_install.set_sensitive(True)
                    return False

        '''
        Add dependency to the bottle configuration
        '''
        if dependency[0] not in configuration.get("Installed_Dependencies"):
            if configuration.get("Installed_Dependencies"):
                dependencies = configuration["Installed_Dependencies"]+[dependency[0]]
            else:
                dependencies = [dependency[0]]
            self.update_configuration(configuration,"Installed_Dependencies", dependencies)

        '''
        Remove the entry from the download manager
        '''
        download_entry.destroy()

        '''
        Hide installation button and show remove button
        '''
        widget.btn_install.set_visible(False)
        widget.btn_remove.set_visible(True)
        widget.btn_remove.set_sensitive(True)

        '''
        Set UI to usable again
        '''
        self.window.set_usable_ui(True)

    def install_dependency(self, configuration, dependency, widget):
        if self.utils_conn.check_connection(True):
            a = RunAsync('install_dependency',
                         self.async_install_dependency, [configuration,
                                                         dependency,
                                                         widget])
            a.start()

    def remove_dependency(self, configuration, dependency, widget):
        logging.info("Removing `%s` dependency from `%s` bottle configuration." % (
            dependency[0], configuration.get("Name")))

        '''
        Prompt the uninstaller
        '''
        self.run_uninstaller(configuration)

        '''
        Remove dependency to the bottle configuration
        '''
        configuration["Installed_Dependencies"].remove(dependency[0])
        self.update_configuration(configuration,
                                  "Installed_Dependencies",
                                  configuration["Installed_Dependencies"])

        '''
        Show installation button and hide remove button
        '''
        widget.btn_install.set_visible(True)
        widget.btn_remove.set_visible(False)

    '''
    Check localy available runners
    '''
    def check_runners(self, install_latest=True):
        runners = glob("%s/*/" % self.runners_path)
        self.runners_available = []

        for runner in runners:
            self.runners_available.append(runner.split("/")[-2])

        if len(self.runners_available) > 0:
            logging.info("Runners found: \n%s" % ', '.join(
                self.runners_available))

        '''
        If there are no locally installed runners, download the latest
        builds for Wine and Proton from the GitHub repositories.
        A very special thanks to Lutris & GloriousEggroll for builds <3!
        '''
        if len(self.runners_available) == 0 and install_latest:
            logging.warning("No runners found.")

            '''
            Fetch runners from repository only if connected
            '''
            if self.utils_conn.check_connection():
                '''
                Wine
                '''
                with urllib.request.urlopen(self.repository_api) as url:
                    releases = json.loads(url.read().decode())
                    tag = releases[0]["tag_name"]
                    file = releases[0]["assets"][0]["name"]

                    self.install_component("runner", tag, file)

                '''
                Proton
                with urllib.request.urlopen(self.proton_repository_api) as url:
                    releases = json.loads(url.read().decode())
                    tag = releases[0]["tag_name"]
                    file = releases[0]["assets"][0]["name"]

                    self.install_component("runner:proton", tag, file)
                '''

        '''
        Sort runners_available and dxvk_available alphabetically
        '''
        self.runners_available = sorted(self.runners_available, reverse=True)
        self.dxvk_available = sorted(self.dxvk_available, reverse=True)

    '''
    Check localy available dxvk
    '''
    def check_dxvk(self, install_latest=True):
        dxvk_list = glob("%s/*/" % self.dxvk_path)
        self.dxvk_available = []

        for dxvk in dxvk_list: self.dxvk_available.append(dxvk.split("/")[-2])

        if len(self.dxvk_available) > 0:
            logging.info("Dxvk found: \n%s" % ', '.join(self.dxvk_available))

        if len(self.dxvk_available) == 0 and install_latest:
            logging.warning("No dxvk found.")

            '''
            Fetch dxvk from repository only if connected
            '''
            if self.utils_conn.check_connection():
                with urllib.request.urlopen(self.dxvk_repository_api) as url:
                    releases = json.loads(url.read().decode())
                    tag = releases[0]["tag_name"]
                    file = releases[0]["assets"][0]["name"]

                    self.install_component("dxvk", tag, file)

    '''
    Get installed programs
    '''
    def get_programs(self, configuration):
        bottle = "%s/%s" % (self.bottles_path, configuration.get("Name"))
        results =  glob("%s/drive_c/users/*/Start Menu/Programs/**/*.lnk" % bottle, recursive=True)
        results += glob("%s/drive_c/ProgramData/Microsoft/Windows/Start Menu/Programs/**/*.lnk" % bottle, recursive=True)
        installed_programs = []

        '''
        For any .lnk file, check for executable path inside
        '''
        for program in results:
            path = program.split("/")[-1]
            if path not in ["Uninstall.lnk"]:
                executable_path = ""
                try:
                    with open(program, "r", encoding='utf-8', errors='ignore') as lnk:
                        lnk = lnk.read()
                        executable_path = re.search('C:(.*).exe', lnk).group(0)
                        if executable_path.find("ninstall") < 0:
                            path = path.replace(".lnk", "")
                            installed_programs.append([path, executable_path])
                except:
                    logging.error("Cannot get executable for `%s`." % path)

        return installed_programs


    '''
    Fetch online dependencies
    '''
    def fetch_dependencies(self):
        if self.utils_conn.check_connection():
            with urllib.request.urlopen(self.dependencies_repository_index) as url:
                index = json.loads(url.read())

                for dependency in index.items():
                    self.supported_dependencies[dependency[0]] = dependency[1]

    '''
    Fetch dependency manifest online
    '''
    def fetch_dependency_manifest(self, dependency_name, plain=False):
        if self.utils_conn.check_connection():
            with urllib.request.urlopen("%s/%s.json" % (
                self.dependencies_repository, dependency_name
            )) as url:
                if plain:
                    return url.read().decode("utf-8")
                else:
                    return json.loads(url.read())

            return False

    '''
    Check local bottles
    '''
    def check_bottles(self):
        bottles = glob("%s/*/" % self.bottles_path)

        '''
        For each bottle add the path name to the `local_bottles` variable
        and append the configuration
        '''
        for bottle in bottles:
            bottle_name_path = bottle.split("/")[-2]
            try:
                configuration_file = open('%s/bottle.json' % bottle)
                configuration_file_json = json.load(configuration_file)
                configuration_file.close()
            except:
                configuration_file_json = self.sample_configuration
                configuration_file_json["Broken"] = True
                configuration_file_json["Name"] = bottle_name_path
                configuration_file_json["Environment"] = "Undefined"

            self.local_bottles[bottle_name_path] = configuration_file_json

        if len(self.local_bottles) > 0:
            logging.info("Bottles found: \n%s" % ', '.join(self.local_bottles))

    '''
    Update parameters in bottle configuration file
    '''
    def update_configuration(self, configuration, key, value, scope=False):
        logging.info("Setting `%s` parameter to `%s` for `%s` Bottle…" % (
            key, value, configuration.get("Name")))

        if configuration.get("Custom_Path"):
            bottle_complete_path = configuration.get("Path")
        else:
            bottle_complete_path = "%s/%s" % (self.bottles_path,
                                              configuration.get("Path"))

        if scope:
            configuration[scope][key] = value
        else:
            configuration[key] = value

        with open("%s/bottle.json" % bottle_complete_path,
                  "w") as configuration_file:
            json.dump(configuration, configuration_file, indent=4)
            configuration_file.close()

        self.window.page_list.update_bottles()
        return configuration

    '''
    Create a new wineprefix async
    '''
    def async_create_bottle(self, args):
        logging.info("Creating the wineprefix…")

        name, environment, path, runner = args

        if not runner: runner = self.runners_available[0]
        runner_name = runner

        '''
        If runner is proton, files are located to the dist path
        '''
        if runner.startswith("Proton"): runner = "%s/dist" % runner

        '''
        Define reusable variables
        '''
        buffer_output = self.window.page_create.buffer_output
        iter = buffer_output.get_end_iter()

        '''
        Check if there is at least one runner and dxvk installed, else
        install latest releases
        '''
        if 0 in [len(self.runners_available), len(self.dxvk_available)]:
            buffer_output.insert(iter, "Runner and/or dxvk not found, installing latest version…\n")
            iter = buffer_output.get_end_iter()
            self.window.page_preferences.set_dummy_runner()
            self.window.show_runners_preferences_view()
            return self.async_checks()

        '''
        Set UI to not usable
        '''
        self.window.set_usable_ui(False)

        '''
        Define bottle parameters
        '''
        bottle_name = name
        bottle_name_path = bottle_name.replace(" ", "-")

        if path == "":
            bottle_custom_path = False
            bottle_complete_path = "%s/%s" % (self.bottles_path, bottle_name_path)
        else:
            bottle_custom_path = True
            bottle_complete_path = path

        '''
        Run the progressbar update async
        '''
        a = RunAsync('pulse', self.window.page_create.pulse);a.start()

        buffer_output.insert(iter, "The wine configuration is being updated…\n")
        iter = buffer_output.get_end_iter()

        '''
        Prepare and execute the command
        '''
        command = "WINEPREFIX={path} WINEARCH=win64 {runner} wineboot".format(
            path = bottle_complete_path,
            runner = "%s/%s/bin/wine64" % (self.runners_path, runner)
        )

        '''
        Get the command output and add to the buffer
        '''
        process = subprocess.Popen(command,
                                   shell=True,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        process_output = process.stdout.read().decode("utf-8")

        buffer_output.insert(iter, process_output)
        iter = buffer_output.get_end_iter()

        '''
        Generate bottle configuration file
        '''
        logging.info("Generating Bottle configuration file…")
        buffer_output.insert(iter, "\nGenerating Bottle configuration file…")
        iter = buffer_output.get_end_iter()

        configuration = self.sample_configuration
        configuration["Name"] = bottle_name
        configuration["Runner"] = runner_name
        if path == "":
            configuration["Path"] = bottle_name_path
        else:
            configuration["Path"] = bottle_complete_path
        configuration["Custom_Path"] = bottle_custom_path
        configuration["Environment"] = environment
        configuration["Creation_Date"] = str(date.today())
        configuration["Update_Date"] = str(date.today())

        '''
        Apply environment configuration
        '''
        logging.info("Applying `%s` environment configuration.." % environment)
        buffer_output.insert(iter, "\nApplying `%s` environment configuration.." % environment)
        iter = buffer_output.get_end_iter()
        if environment != "Custom":
            environment_parameters = self.environments[environment.lower()]["Parameters"]
            for parameter in configuration["Parameters"]:
                if parameter in environment_parameters:
                    configuration["Parameters"][parameter] = environment_parameters[parameter]

        '''
        Save bottle configuration
        '''
        with open("%s/bottle.json" % bottle_complete_path,
                  "w") as configuration_file:
            json.dump(configuration, configuration_file, indent=4)
            configuration_file.close()

        '''
        Perform dxvk installation if configured
        '''
        if configuration["Parameters"]["dxvk"]:
            logging.info("Installing dxvk…")
            buffer_output.insert(iter, "\nInstalling dxvk…")
            iter = buffer_output.get_end_iter()
            self.install_dxvk(configuration)

        '''
        Set the list button visible and set UI to usable again
        '''
        logging.info("Bottle `%s` successfully created!" % bottle_name)
        buffer_output.insert_markup(
            iter,
            "\n<span foreground='green'>%s</span>" % "Your new bottle with name `%s` is now ready!" % bottle_name,
            -1)
        iter = buffer_output.get_end_iter()

        self.window.page_create.set_status("created")
        self.window.set_usable_ui(True)


        '''
        Clear local bottles list and do the check again
        '''
        self.local_bottles = {}
        self.check_bottles()

    def create_bottle(self, name, environment, path=False, runner=False):
        a = RunAsync('create', self.async_create_bottle, [name,
                                                          environment,
                                                          path,
                                                          runner])
        a.start()

    '''
    Get latest installed runner
    '''
    def get_latest_runner(self, runner_type="wine"):
        if runner_type == "wine":
            latest_runner = [idx for idx in self.runners_available if idx.lower().startswith("lutris")][0]
        else:
            latest_runner = [idx for idx in self.runners_available if idx.lower().startswith("proton")][0]
        return latest_runner

    '''
    Get human size
    '''
    def get_human_size(self, size):
        for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
            if abs(size) < 1024.0:
                return "%3.1f%s%s" % (size, unit, 'B')
            size /= 1024.0

        return "%.1f%s%s" % (size, 'Yi', 'B')

    '''
    Get path size
    '''
    def get_path_size(self, path, human=True):
        path = Path(path)
        size = sum(f.stat().st_size for f in path.glob('**/*') if f.is_file())

        if human: return self.get_human_size(size)

        return size

    '''
    Get disk size
    '''
    def get_disk_size(self, human=True):
        '''
        TODO: disk should be taken from configuration Path
        '''
        disk_total, disk_used, disk_free = shutil.disk_usage('/')

        if human:
            disk_total = self.get_human_size(disk_total)
            disk_used = self.get_human_size(disk_used)
            disk_free = self.get_human_size(disk_free)

        return {
            "total": disk_total,
            "used": disk_free,
            "free": disk_free,
        }

    '''
    Get bottle path size
    '''
    def get_bottle_size(self, configuration, human=True):
        path = configuration.get("Path")
        runner = configuration.get("Runner")

        if not configuration.get("Custom_Path"):
            path = "%s/%s" % (self.bottles_path, path)

        return self.get_path_size(path, human)

    '''
    Delete a wineprefix
    '''
    def async_delete_bottle(self, args):
        logging.info("Deleting the wineprefix…")

        configuration = args[0]

        '''
        Delete path with all files
        '''
        path = configuration.get("Path")

        if path != "":
            if not configuration.get("Custom_Path"):
                path = "%s/%s" % (self.bottles_path, path)

            shutil.rmtree(path)
            logging.info("Successfully deleted the bottle in path: %s" % path)
        else:
            logging.error("Empty path found, failing to avoid disasters.")

    def delete_bottle(self, configuration):
        a = RunAsync('delete', self.async_delete_bottle, [configuration]);a.start()

    '''
    Repair a bottle generating a new configuration
    '''
    def repair_bottle(self, configuration):
        logging.info("Trying to repair the `%s` bottle.." % configuration.get("Name"))

        bottle_complete_path = "%s/%s" % (self.bottles_path,
                                          configuration.get("Name"))

        '''
        Creating a new configuration, using path name as bottle name
        and Custom as environment
        '''
        new_configuration = self.sample_configuration
        new_configuration["Name"] = configuration.get("Name")
        new_configuration["Runner"] = self.runners_available[0]
        new_configuration["Path"] = configuration.get("Name")
        new_configuration["Environment"] = "Custom"
        new_configuration["Creation_Date"] = str(date.today())
        new_configuration["Update_Date"] = str(date.today())
        del new_configuration["Broken"]

        with open("%s/bottle.json" % bottle_complete_path,
                  "w") as configuration_file:
            json.dump(new_configuration, configuration_file, indent=4)
            configuration_file.close()

        '''
        Execute wineboot in bottle trying to generate missing files
        '''
        self.run_wineboot(new_configuration)

        '''
        Re-index all bottles
        '''
        self.check_bottles()

        '''
        The re-populate the list in page_list
        '''
        self.window.page_list.update_bottles()

    '''
    Methods for wine processes management
    '''
    def get_running_processes(self):
        processes = []
        pids = subprocess.Popen(
            "ps -eo pid,pmem,pcpu,stime,time,cmd | grep wine | tr -s ' ' '|'",
            shell=True,
            stdout=subprocess.PIPE).communicate()[0].decode("utf-8")

        for pid in pids.split("\n"):
            process_data = pid.split("|")
            if len(process_data) >= 6 and "grep" not in process_data:
                processes.append({
                    "pid": process_data[1],
                    "pmem": process_data[2],
                    "pcpu": process_data[3],
                    "stime": process_data[4],
                    "time": process_data[5],
                    "cmd": process_data[6]
                })

        return processes

    '''
    Methods for add and remove values to register
    '''
    def reg_add(self, configuration, key, value, data):
        logging.info("Adding value `%s` with data `%s` for key `%s` in register for `%s` bottle." % (
            value, data, key, configuration.get("Name")))

        self.run_command(configuration, "reg add '%s' /v %s /d %s /f" % (
            key, value, data))

    def reg_delete(self, configuration, key, value):
        logging.info("Removing value `%s` for key `%s` in register for `%s` bottle." % (
            value, key, configuration.get("Name")))

        self.run_command(configuration, "reg delete '%s' /v %s /f" % (
            key, value))

    '''
    Methods for install and remove dxvk using official setup script
    TODO: A good task for the future is to use the built-in methods to
    install the new dlls and register the override for dxvk.
    '''
    def install_dxvk(self, configuration, remove=False):
        logging.info("Installing dxvk for `%s` bottle." % configuration.get("Name"))

        option = "uninstall" if remove else "install"

        command = 'WINEPREFIX="{path}" PATH="{runner}:$PATH" {dxvk_setup} {option}'.format (
            path = "%s/%s" % (self.bottles_path, configuration.get("Path")),
            runner = "%s/%s/bin" % (self.runners_path, configuration.get("Runner")),
            dxvk_setup = "%s/%s/setup_dxvk.sh" % (self.dxvk_path, self.dxvk_available[0]),
            option = option)

        return subprocess.Popen(command, shell=True)

    def remove_dxvk(self, configuration):
        logging.info("Removing dxvk for `%s` bottle." % configuration.get("Name"))

        self.install_dxvk(configuration, remove=True)

    '''
    Method for override dll in system32/syswow64 paths
    '''
    def dll_override(self, configuration, arch, dlls, source, revert=False):
        arch = "system32" if arch == 32 else "syswow64"
        path = "%s/%s/drive_c/windows/%s" % (self.bottles_path,
                                             configuration.get("Path"),
                                             arch)

        '''
        Revert dll from backup
        '''
        if revert:
            for dll in dlls:
                shutil.move("%s/%s.back" % (path, dll), "%s/%s" % (path, dll))
        else:
            '''
            Backup old dlls and install new one
            '''
            for dll in dlls:
                shutil.move("%s/%s" % (path, dll), "%s/%s.old" % (path, dll))
                shutil.copy("%s/%s" % (source, dll), "%s/%s" % (path, dll))

    '''
    Enable or disable virtual desktop for a bottle
    '''
    def toggle_virtual_desktop(self, configuration, state, resolution="800x600"):
        key = "HKEY_CURRENT_USER\\Software\\Wine\\Explorer\\Desktops"
        if state:
            self.reg_add(configuration, key, "Default", resolution)
        else:
            self.reg_delete(configuration, key, "Default")

    '''
    Methods for running wine applications in wineprefixes
    '''
    def run_executable(self, configuration, file_path, arguments=False):
        logging.info("Running an executable on the wineprefix…")

        '''
        Check if for .mis then execute with `msiexec` tool
        '''
        if "msi" in file_path.split("."):
            command = "msiexec /i '%s'" % file_path
        else:
            command = "'%s'" % file_path

        if arguments:
            command = "%s %s" % (command, arguments)

        self.run_command(configuration, command)

    def run_wineboot(self, configuration):
        logging.info("Running wineboot on the wineprefix…")
        self.run_command(configuration, "wineboot -u")

    def run_winecfg(self, configuration):
        logging.info("Running winecfg on the wineprefix…")
        self.run_command(configuration, "winecfg")

    def run_winetricks(self, configuration):
        logging.info("Running winetricks on the wineprefix…")
        self.run_command(configuration, "winetricks")

    def run_debug(self, configuration):
        logging.info("Running a debug console on the wineprefix…")
        self.run_command(configuration, "winedbg", terminal=True)

    def run_cmd(self, configuration):
        logging.info("Running a CMD on the wineprefix…")
        self.run_command(configuration, "wineconsole cmd")

    def run_taskmanager(self, configuration):
        logging.info("Running a Task Manager on the wineprefix…")
        self.run_command(configuration, "taskmgr")

    def run_controlpanel(self, configuration):
        logging.info("Running a Control Panel on the wineprefix…")
        self.run_command(configuration, "control")

    def run_uninstaller(self, configuration):
        logging.info("Running an Uninstaller on the wineprefix…")
        self.run_command(configuration, "uninstaller")

    def run_regedit(self, configuration):
        logging.info("Running a Regedit on the wineprefix…")
        self.run_command(configuration, "regedit")

    '''
    Run wine command in a bottle
    '''
    def run_command(self, configuration, command, terminal=False):
        '''
        Prepare and execute the command
        '''
        path = configuration.get("Path")
        runner = configuration.get("Runner")

        '''
        If runner is proton then set path to /dist
        '''
        if runner.startswith("Proton"):
            runner = "%s/dist" % runner

        if not configuration.get("Custom_Path"):
            path = "%s/%s" % (self.bottles_path, path)

        '''
        Get environment variables from configuration to pass
        as command arguments
        '''
        environment_vars = []
        dll_overrides = []
        parameters = configuration["Parameters"]

        if parameters["dll_overrides"]:
            dll_overrides.append(parameters["dll_overrides"])

        if parameters["environment_variables"]:
            environment_vars.append(parameters["environment_variables"])

        if parameters["dxvk"]:
            dll_overrides.append("d3d11,dxgi=n")
            environment_vars.append("DXVK_STATE_CACHE_PATH='%s'" % path)
            environment_vars.append("STAGING_SHARED_MEMORY=1")
            environment_vars.append("__GL_DXVK_OPTIMIZATIONS=1")
            environment_vars.append("__GL_SHADER_DISK_CACHE=1")
            environment_vars.append("__GL_SHADER_DISK_CACHE_PATH='%s'" % path)

        if parameters["dxvk_hud"]:
            environment_vars.append("DXVK_HUD='devinfo,memory,drawcalls,fps,version,api,compiler'")
        else:
            environment_vars.append("DXVK_HUD='compiler'")

        if parameters["esync"]:
            environment_vars.append("WINEESYNC=1 WINEDEBUG=+esync")

        if parameters["fsync"]:
            environment_vars.append("WINEFSYNC=1")

        if parameters["aco_compiler"]:
            environment_vars.append("RADV_PERFTEST=aco")

        if parameters["discrete_gpu"]:
            if "nvidia" in subprocess.Popen(
                "lspci | grep 'VGA'",
                stdout=subprocess.PIPE,
                shell=True).communicate()[0].decode("utf-8"):
                environment_vars.append("__NV_PRIME_RENDER_OFFLOAD=1")
                environment_vars.append("__GLX_VENDOR_LIBRARY_NAME='nvidia'")
                environment_vars.append("__VK_LAYER_NV_optimus='NVIDIA_only'")
            else:
                environment_vars.append("DRI_PRIME=1")

        if parameters["pulseaudio_latency"]:
            environment_vars.append("PULSE_LATENCY_MSEC=60")

        environment_vars.append("WINEDLLOVERRIDES='%s'" % ",".join(dll_overrides))
        environment_vars = " ".join(environment_vars)

        command = "WINEPREFIX={path} WINEARCH=win64 {env} {runner} {command}".format(
            path = path,
            env = environment_vars,
            runner = "%s/%s/bin/wine64" % (self.runners_path, runner),
            command = command
        )

        if terminal:
            return UtilsTerminal(command)

        return subprocess.Popen(command, shell=True)

    '''
    Method for sending status to wineprefixes
    '''
    def send_status(self, configuration, status):
        logging.info("Sending %s status to the wineprefix…" % status)

        available_status = {
            "shutdown": "-s",
            "reboot": "-r",
            "kill": "-k"
        }
        option = available_status[status]
        bottle_name = configuration.get("Name")

        '''
        Prepare and execute the command
        '''
        self.run_command(configuration, "wineboot %s" % option)

        '''
        Send a notification for status change if the
        user settings allow it
        '''
        if self.settings.get_boolean("notifications"):
            self.window.send_notification("Bottles",
                                          "`%s` completed for `%s`." % (
                                              status,
                                              bottle_name
                                          ), "applications-system-symbolic")

    '''
    Method for open wineprefixes path in file manager
    '''
    def open_filemanager(self, configuration={}, path_type="bottle", runner=False, dxvk=False):
        logging.info("Opening the file manager on the path…")

        if path_type == "bottle":
            path = "%s/%s/drive_c" % (self.bottles_path,
                                      configuration.get("Path"))

        if path_type == "runner":
            path = "%s/%s" % (self.runners_path, runner)

        if path_type == "dxvk":
            path = "%s/%s" % (self.dxvk_path, dxvk)

        '''
        Prepare and execute the command
        '''
        command = "xdg-open %s" % path
        return subprocess.Popen(command, shell=True)

