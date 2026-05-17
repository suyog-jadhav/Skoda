FROM israelhikingmap/graphhopper:latest

# This Dockerfile is provided in case you need to extend the base GraphHopper image.
# For example, to install additional tools, copy static files, or customize the entrypoint.

# We don't override WORKDIR here because the base image expects to be in a specific 
# directory to execute its entrypoint script (graphhopper.sh).

# The base image already exposes port 8989 and has the necessary Java environment.
EXPOSE 8989
