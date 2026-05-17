@echo off
echo Starting GraphHopper 12...
docker-compose up -d --build

echo.
echo GraphHopper container is starting in the background.
echo Note: Since the cache is empty, it may take a while to build the graph for the first time.
echo.
echo Tailing logs now. You can press Ctrl+C to stop viewing logs (GraphHopper will continue running in the background).
echo.
docker-compose logs -f
pause
