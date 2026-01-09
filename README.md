<!-- Have the Makefile have all the perfect commands, and put them here in the order of what's needed for this project -->
make reset: The first word make, is for triggering Makefile itself. After is the command inside Makefile.

docker compose build: Creates the images defined in your docker-compose.yml. Use this when you change Python packages or the Dockerfile itself.

docker compose up: Starts all services and streams the logs to your terminal.

docker compose up -d: Starts the containers in "Detached" mode (runs in the background), giving you your terminal back.

docker compose up --build: The "do it all" command. It rebuilds the images and starts the containers in one go. Useful if you aren't sure if your code changes are showing up.

docker compose ps: Shows a list of running containers, their status (Up/Exited), and which ports they are using.

docker compose logs -f: Displays the live output (logs) from all containers.

docker compose logs -f <service-name>: (e.g., docker compose logs -f django-web) Follows the logs for just one specific service.

docker compose exec <service-name> <command>: Runs a command inside a running container.
Example: docker compose exec django-web python manage.py migrate

docker compose restart: Restarts all containers. Fast, but does not apply changes made to the Dockerfile or docker-compose.yml.

docker compose stop: Stops the containers but keeps them "ready" to start again quickly.

docker compose start: Starts containers that were previously stopped.

docker compose down: Stops and removes the containers and the internal network. Your code stays safe, but the "running instances" are deleted.

docker compose down -v: The "Nuclear Option." Stops containers and deletes the database volumes. Use this if you have a database version mismatch or want to wipe your data.

docker system prune: Deletes all unused data, including old images and hanging "orphan" layers. Great for freeing up disk space on your Mac.

docker compose top:	See which processes are using the most CPU/RAM.

docker compose images:	See how much disk space your images are taking up.

docker compose config:	Checks your .yml file for syntax errors without running it.

<!-- What I've used -->
docker build . -t my-django-image

docker compose up

docker compose down -v 

docker compose up --build 

docker compose restart django-web

docker compose logs -f django-web