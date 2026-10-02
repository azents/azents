# SupportPredicate

A conjunction of saved effort and function-tool request conditions.  Null means that dimension does not constrain the request. An omitted request effort cannot satisfy an effort predicate without a known saved default. Evaluation belongs to the consumers of this contract, not to source lookup.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**reasoning_efforts** | [**List[ReasoningEffortValue]**](ReasoningEffortValue.md) |  | 
**function_tools** | **bool** |  | 

## Example

```python
from azentspublicclient.models.support_predicate import SupportPredicate

# TODO update the JSON string below
json = "{}"
# create an instance of SupportPredicate from a JSON string
support_predicate_instance = SupportPredicate.from_json(json)
# print the JSON string representation of the object
print(SupportPredicate.to_json())

# convert the object into a dict
support_predicate_dict = support_predicate_instance.to_dict()
# create an instance of SupportPredicate from a dict
support_predicate_from_dict = SupportPredicate.from_dict(support_predicate_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


