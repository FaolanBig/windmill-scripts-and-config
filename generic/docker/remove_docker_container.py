#requirements:
#docker==7.1.0

import logging
import os
from typing import Any
import docker
from docker.errors import DockerException, ImageNotFound, NotFound


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)
#requirements:

# You can import any PyPi package. 
# See here for more info: https://www.windmill.dev/docs/advanced/dependencies_in_python

# you can use typed resources by doing a type alias to dict
#postgresql = dict

def main(
    container_id: str,
    image_id: str | None = None,
    timeout = 30,
    only_dangling_images: bool = True
) -> dict[str, str]:

    logger.info("Removing Docker container %s", container_id)

    if timeout < 1:
        logger.warning("Container removal rejected: timeout must be at least 1 second")
        return {
            "finished_successful": "false",
            "error_message": "timeout must be at least 1 second",
            "container_removed": "false",
            "image_removed": "false"
        }

    if not container_id:
        logger.warning("Container removal rejected: container_id is required and missing")
        return {
            "finished_successful": "false",
            "error_message": "container_id is required and missing",
            "container_removed": "false",
            "image_removed": "false"
        }
    
    host = os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375"

    logger.debug("Connecting to Docker daemon at %s", host)
    client = None
    try:
        client = docker.DockerClient(
            base_url=host,
            tls=False,
            timeout=timeout
        )
        client.ping()
    except DockerException as exc:
        logger.exception("Could not connect to Docker daemon at %s", host)
        if client is not None:
            client.close()
        return {
            "finished_successful": "false",
            "error_message": f"Could not connect to Docker: {exc}",
            "container_removed": "false",
            "image_removed": "false"
        }
    
    container_removed = False
    container_error = ""
    container = None
    image_removed = False
    image_error = ""
    prune_errors: list[str] = []
    
    try:
        container = client.containers.get(container_id)

        if not image_id:
            container_image = container.attrs.get("Image")
            if container_image:
                image_id = as_string(container_image)
        
        container.reload()

        if container.status not in ("exited", "dead", "created", "removing"):
            container.stop(timeout=timeout)
        
        container.remove(force=True, v=True)
        container_removed = True
        logger.info("Docker container %s removed", container_id)
    
    except NotFound:
        container_removed = True
        logger.info("Docker container %s was already absent", container_id)
    
    except DockerException as exc:
        container_error = str(exc)
        logger.error("Failed to remove Docker container %s: %s", container_id, exc)
    
    if image_id:
        try:
            image = client.images.get(image_id)
            image.remove(force=True, noprune=False)
            image_removed = True
            logger.info("Docker image %s removed", image_id)
        except (NotFound, ImageNotFound):
            image_removed = True
            logger.info("Docker image %s was already absent", image_id)
        except DockerException as exc:
            image_error = str(exc)
            logger.error("Failed to remove Docker image %s: %s", image_id, exc)
    
    if container_removed:
        try:
            client.containers.prune()
        except DockerException as exc:
            prune_errors.append(f"container prune: {exc}")
            logger.error("Failed to prune containers: %s", exc)
    
    try:
        client.images.prune(filters={"dangling": only_dangling_images})
    except DockerException as exc:
        prune_errors.append(f"image prune: {exc}")
        logger.error("Failed to prune images: %s", exc)
    
    try:
        client.volumes.prune()
    except DockerException as exc:
        prune_errors.append(f"volume prune: {exc}")
        logger.error("Failed to prune volumes: %s", exc)
    
    try:
        client.networks.prune()
    except DockerException as exc:
        prune_errors.append(f"network prune: {exc}")
        logger.error("Failed to prune networks: %s", exc)

    try:
        client.api.prune_builds()
    except (AttributeError, DockerException) as exc:
        prune_errors.append(f"build cache prune: {exc}")
        logger.error("Failed to prune build cache: %s", exc)

    if client is not None:
        client.close()
        logger.debug("Closed Docker client connection")

    errors = [
        error
        for error in (
            container_error,
            image_error,
            *prune_errors
        )
        if error
    ]

    if errors:
        logger.error("Docker cleanup completed with errors: %s", "; ".join(errors))
        return {
            "finished_successful": "false",
            "error_message": "; ".join(errors),
            "container_id": container_id,
            "container_removed": as_string(container_removed).lower(),
            "image_id": as_string(image_id),
            "image_removed": as_string(image_removed).lower()
        }

    logger.info(
        "Docker cleanup completed: container_removed=%s image_removed=%s",
        container_removed,
        image_removed
    )
    return {
        "finished_successful": "true",
        "error_message": "",
        "container_id": as_string(container_id),
        "container_removed": "true",
        "image_id": as_string(image_id),
        "image_removed": as_string(image_removed)
    }


def as_string(value: Any) -> str:
    return "" if value is None else str(value)