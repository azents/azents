# TestConnectionResponse

Test connection response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**success** | **bool** | Connection success state |
**message** | **str** | Result message |
**discovered_auth_url** | **str** |  | [optional]
**discovered_token_url** | **str** |  | [optional]
**supports_dcr** | **bool** |  | [optional]

## Example

```python
from azentspublicclient.models.test_connection_response import TestConnectionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of TestConnectionResponse from a JSON string
test_connection_response_instance = TestConnectionResponse.from_json(json)
# print the JSON string representation of the object
print(TestConnectionResponse.to_json())

# convert the object into a dict
test_connection_response_dict = test_connection_response_instance.to_dict()
# create an instance of TestConnectionResponse from a dict
test_connection_response_from_dict = TestConnectionResponse.from_dict(test_connection_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
