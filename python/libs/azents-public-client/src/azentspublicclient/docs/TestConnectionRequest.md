# TestConnectionRequest

Connection test request.  In edit mode, send ``toolkit_config_id`` to load credentials stored in DB, then override them with the ``credentials`` field value.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_type** | **str** | Toolkit type, such as mcp or github | [optional] [default to 'mcp']
**config** | **Dict[str, object]** |  |
**credentials** | **Dict[str, object]** |  | [optional]
**toolkit_config_id** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.test_connection_request import TestConnectionRequest

# TODO update the JSON string below
json = "{}"
# create an instance of TestConnectionRequest from a JSON string
test_connection_request_instance = TestConnectionRequest.from_json(json)
# print the JSON string representation of the object
print(TestConnectionRequest.to_json())

# convert the object into a dict
test_connection_request_dict = test_connection_request_instance.to_dict()
# create an instance of TestConnectionRequest from a dict
test_connection_request_from_dict = TestConnectionRequest.from_dict(test_connection_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
