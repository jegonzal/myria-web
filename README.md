A web front-end for Myria
=========================

This is a Google App Engine app.

[![Build Status](https://magnum.travis-ci.com/uwescience/myria-web.svg?token=BLHWag1nbAUpjrkqdzEA&branch=master)](https://magnum.travis-ci.com/uwescience/myria-web)

# Dependencies

You must have the [Google App Engine SDK for Python](https://developers.google.com/appengine/downloads#Google_App_Engine_SDK_for_Python) installed locally.  During setup, be sure to select the option to create symbolic links to the Python utilities so that they are available from the command line.

# Initial setup
1. This project uses the [UW eScience Datalogcompiler](https://github.com/uwescience/datalogcompiler) project. We have configured it as a submodule. After cloning this repository, you must run:

  ```sh
  git submodule init
  git submodule update
  ```
  
    Then setup the module as described in the `datalogcompiler` README.
  
2. The PLY library used to parse programs in the Myria language uses a precompiled `parsetab.py` in the `datalogcompiler` submodule. This file is not required, but dramatically speeds up the parser load time (which happens for every request to the app). To generate it, run

  ```sh
  scripts/myrial examples/reachable.myl
  ```
  
  in the `datalogcompiler` subdirectory.
  
3. Launch the local App Engine emulator. I prefer to use Google's `GoogleApp EngineLauncher` application (installed with the SDK), which provides a nice GUI interface to control the emulator. From the menu select Add Existing Application, and add the `myria-web/appengine` directory.

  Alternatively, from the command line, you may launch:
  
  ```sh
  dev_appserver.py AppEngine
  ```

  And then point your browser at `localhost:8080` to view the application.

# Changing the Myria Hostname

To change the Myria instance from the default (vega), modify appengine/myria_web_main.py, changing the hostname and port variables. Changes will reflect automatically in the GAE application at localhost:8080.

# Which branch to be on

There are two notable branches in the myria-web repository: *master* and *production*.
* `master` is the latest development code
* `production` is the code currently running the web interface on <https://demo.myria.cs.washington.edu>

Depending on your goals (modifying latest myria-web vs running a stable version of the interface), you may wish to switch to the `production` branch.


# Updating the code

To update the submodule to the latest from master, run this code:

```sh
git submodule update --recursive --remote
```

(Might also require beforehand:

```sh
git submodule init
```
)

# Issues

The Google App Engine GUI has a Logs button that can be helpful for diagnosing issues with the Myria web app.

