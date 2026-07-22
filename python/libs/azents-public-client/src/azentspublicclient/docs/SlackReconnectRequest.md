# SlackReconnectRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**credentials** | [**SlackConnectionCredentials**](SlackConnectionCredentials.md) |  | 

## Example

```python
from azentspublicclient.models.slack_reconnect_request import SlackReconnectRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SlackReconnectRequest from a JSON string
slack_reconnect_request_instance = SlackReconnectRequest.from_json(json)
# print the JSON string representation of the object
print(SlackReconnectRequest.to_json())

# convert the object into a dict
slack_reconnect_request_dict = slack_reconnect_request_instance.to_dict()
# create an instance of SlackReconnectRequest from a dict
slack_reconnect_request_from_dict = SlackReconnectRequest.from_dict(slack_reconnect_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


