# PersonalToolkitEligibleAgentResponse

Full current ordinary-access Agent identity for Workspace-grouped selection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** |  | 
**agent_name** | **str** |  | 
**workspace_id** | **str** |  | 
**workspace_name** | **str** |  | 
**workspace_handle** | **str** |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_eligible_agent_response import PersonalToolkitEligibleAgentResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitEligibleAgentResponse from a JSON string
personal_toolkit_eligible_agent_response_instance = PersonalToolkitEligibleAgentResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitEligibleAgentResponse.to_json())

# convert the object into a dict
personal_toolkit_eligible_agent_response_dict = personal_toolkit_eligible_agent_response_instance.to_dict()
# create an instance of PersonalToolkitEligibleAgentResponse from a dict
personal_toolkit_eligible_agent_response_from_dict = PersonalToolkitEligibleAgentResponse.from_dict(personal_toolkit_eligible_agent_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


