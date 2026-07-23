# SlackConnectionSetupRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**app_id** | **str** |  | 
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) |  | 
**credentials** | [**SlackConnectionCredentials**](SlackConnectionCredentials.md) |  | 

## Example

```python
from azentspublicclient.models.slack_connection_setup_request import SlackConnectionSetupRequest

# TODO update the JSON string below
json = "{}"
# create an instance of SlackConnectionSetupRequest from a JSON string
slack_connection_setup_request_instance = SlackConnectionSetupRequest.from_json(json)
# print the JSON string representation of the object
print(SlackConnectionSetupRequest.to_json())

# convert the object into a dict
slack_connection_setup_request_dict = slack_connection_setup_request_instance.to_dict()
# create an instance of SlackConnectionSetupRequest from a dict
slack_connection_setup_request_from_dict = SlackConnectionSetupRequest.from_dict(slack_connection_setup_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


