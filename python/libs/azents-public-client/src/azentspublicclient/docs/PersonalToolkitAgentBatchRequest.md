# PersonalToolkitAgentBatchRequest

Agent editor can update only the exact Agent and cannot reset global policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**mutations** | [**List[PersonalToolkitBatchEntry]**](PersonalToolkitBatchEntry.md) |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_agent_batch_request import PersonalToolkitAgentBatchRequest

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitAgentBatchRequest from a JSON string
personal_toolkit_agent_batch_request_instance = PersonalToolkitAgentBatchRequest.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitAgentBatchRequest.to_json())

# convert the object into a dict
personal_toolkit_agent_batch_request_dict = personal_toolkit_agent_batch_request_instance.to_dict()
# create an instance of PersonalToolkitAgentBatchRequest from a dict
personal_toolkit_agent_batch_request_from_dict = PersonalToolkitAgentBatchRequest.from_dict(personal_toolkit_agent_batch_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


