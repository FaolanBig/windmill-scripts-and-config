#requirements:
#docker==7.1.0

import os
from typing import Any
import docker
from docker.errors import DockerException, ImageNotFound, NotFound

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

    if timeout < 1:
        return {
            "finished_successful": "false",
            "error_message": "timeout must be at least 1 second",
            "container_removed": "false",
            "image_removed": "false"
        }

    if not container_id:
        return {
            "finished_successful": "false",
            "error_message": "container_id is required and missing",
            "container_removed": "false",
            "image_removed": "false"
        }
    
    host = os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375"

    client = None
    try:
        client = docker.DockerClient(
            base_url=host,
            tls=False,
            timeout=timeout
        )
        client.ping()
    except DockerException as exc:
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
    
    except NotFound:
        container_removed = True
    
    except DockerException as exc:
        container_error = str(exc)
    
    if image_id:
        try:
            image = client.images.get(image_id)
            image.remove(force=True, noprune=False)
            image_removed = True
        except (NotFound, ImageNotFound):
            image_removed = True
        except DockerException as exc:
            image_error = str(exc)
    
    if container_removed:
        try:
            client.containers.prune()
        except DockerException as exc:
            prune_errors.append(f"container prune: {exc}")
    
    try:
        client.images.prune(filters={"dangling": only_dangling_images})
    except DockerException as exc:
        prune_errors.append(f"image prune: {exc}")
    
    try:
        client.volumes.prune()
    except DockerException as exc:
        prune_errors.append(f"volume prune: {exc}")
    
    try:
        client.networks.prune()
    except DockerException as exc:
        prune_errors.append(f"network prune: {exc}")

    try:
        client.api.prune_builds()
    except (AttributeError, DockerException) as exc:
        prune_errors.append(f"build cache prune: {exc}")

    if client is not None:
        client.close()

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
        return {
            "finished_successful": "false",
            "error_message": "; ".join(errors),
            "container_id": container_id,
            "container_removed": as_string(container_removed).lower(),
            "image_id": as_string(image_id),
            "image_removed": as_string(image_removed).lower()
        }

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