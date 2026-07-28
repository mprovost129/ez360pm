class ToolInputError(ValueError):
    pass


def _matches_type(value, expected):
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _label(path):
    return path or "value"


def _validate_value(definition, value, path):
    name = _label(path)
    if not _matches_type(value, definition.get("type")):
        raise ToolInputError(f"{name} has the wrong data type.")
    if value is None:
        return None
    if "enum" in definition and value not in definition["enum"]:
        raise ToolInputError(f"{name} is not an allowed value.")

    if isinstance(value, str):
        if len(value) < definition.get("minLength", 0):
            raise ToolInputError(f"{name} is too short.")
        if len(value) > definition.get("maxLength", 1000000):
            raise ToolInputError(f"{name} is too long.")
        return value.strip()

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        if value < definition.get("minimum", value):
            raise ToolInputError(f"{name} is too small.")
        if "exclusiveMinimum" in definition and value <= definition["exclusiveMinimum"]:
            raise ToolInputError(f"{name} must be greater than {definition['exclusiveMinimum']}.")
        if value > definition.get("maximum", value):
            raise ToolInputError(f"{name} is too large.")
        if "exclusiveMaximum" in definition and value >= definition["exclusiveMaximum"]:
            raise ToolInputError(f"{name} must be less than {definition['exclusiveMaximum']}.")
        return value

    if isinstance(value, list):
        if len(value) < definition.get("minItems", 0):
            raise ToolInputError(f"{name} has too few items.")
        if len(value) > definition.get("maxItems", 1000000):
            raise ToolInputError(f"{name} has too many items.")
        item_definition = definition.get("items")
        if not item_definition:
            return value
        return [
            _validate_value(item_definition, item, f"{name}[{index}]")
            for index, item in enumerate(value)
        ]

    if isinstance(value, dict):
        properties = definition.get("properties", {})
        unknown = set(value) - set(properties)
        if unknown:
            raise ToolInputError(
                f"Unknown fields in {name}: {', '.join(sorted(unknown))}."
            )
        missing = set(definition.get("required", [])) - set(value)
        if missing:
            raise ToolInputError(
                f"Missing fields in {name}: {', '.join(sorted(missing))}."
            )
        return {
            key: _validate_value(properties[key], item, f"{name}.{key}")
            for key, item in value.items()
        }

    return value


def validate_arguments(schema, arguments):
    if not isinstance(arguments, dict):
        raise ToolInputError("Tool arguments must be a JSON object.")
    properties = schema.get("properties", {})
    unknown = set(arguments) - set(properties)
    if unknown:
        raise ToolInputError(f"Unknown tool fields: {', '.join(sorted(unknown))}.")
    missing = set(schema.get("required", [])) - set(arguments)
    if missing:
        raise ToolInputError(f"Missing tool fields: {', '.join(sorted(missing))}.")

    return {
        name: _validate_value(properties[name], value, name)
        for name, value in arguments.items()
    }
