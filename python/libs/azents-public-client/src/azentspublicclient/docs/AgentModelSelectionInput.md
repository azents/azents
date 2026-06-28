# AgentModelSelectionInput

Catalog model selection input.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**llm_provider_integration_id** | **str** | LLM provider integration ID |
**model_identifier** | **str** | Provider model identifier |

## Example

```python
from azentspublicclient.models.agent_model_selection_input import AgentModelSelectionInput

# TODO update the JSON string below
json = "{}"
# create an instance of AgentModelSelectionInput from a JSON string
agent_model_selection_input_instance = AgentModelSelectionInput.from_json(json)
# print the JSON string representation of the object
print(AgentModelSelectionInput.to_json())

# convert the object into a dict
agent_model_selection_input_dict = agent_model_selection_input_instance.to_dict()
# create an instance of AgentModelSelectionInput from a dict
agent_model_selection_input_from_dict = AgentModelSelectionInput.from_dict(agent_model_selection_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


