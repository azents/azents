# BrowserConfigurationReplaceRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_intent_id** | **str** |  | 
**implementation** | [**BrowserImplementation**](BrowserImplementation.md) |  | 
**retry** | **bool** |  | 

## Example

```python
from azentspublicclient.models.browser_configuration_replace_request import BrowserConfigurationReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserConfigurationReplaceRequest from a JSON string
browser_configuration_replace_request_instance = BrowserConfigurationReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(BrowserConfigurationReplaceRequest.to_json())

# convert the object into a dict
browser_configuration_replace_request_dict = browser_configuration_replace_request_instance.to_dict()
# create an instance of BrowserConfigurationReplaceRequest from a dict
browser_configuration_replace_request_from_dict = BrowserConfigurationReplaceRequest.from_dict(browser_configuration_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


