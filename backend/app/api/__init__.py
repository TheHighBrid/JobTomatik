"""API package bootstrap integrations."""

from app.services.day38_runtime import install_day38_api_integration

# Importing any API surface installs the fail-closed Day 38 preflight/ORM wrappers.
# Outside Android managed mode the wrappers delegate unchanged to the existing paths.
install_day38_api_integration()
