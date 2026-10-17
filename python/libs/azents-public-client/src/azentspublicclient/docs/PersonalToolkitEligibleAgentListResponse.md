# PersonalToolkitEligibleAgentListResponse

All current eligible Agents before any UI search or pagination.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[PersonalToolkitEligibleAgentResponse]**](PersonalToolkitEligibleAgentResponse.md) |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_eligible_agent_list_response import PersonalToolkitEligibleAgentListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitEligibleAgentListResponse from a JSON string
personal_toolkit_eligible_agent_list_response_instance = PersonalToolkitEligibleAgentListResponse.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitEligibleAgentListResponse.to_json())

# convert the object into a dict
personal_toolkit_eligible_agent_list_response_dict = personal_toolkit_eligible_agent_list_response_instance.to_dict()
# create an instance of PersonalToolkitEligibleAgentListResponse from a dict
personal_toolkit_eligible_agent_list_response_from_dict = PersonalToolkitEligibleAgentListResponse.from_dict(personal_toolkit_eligible_agent_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


