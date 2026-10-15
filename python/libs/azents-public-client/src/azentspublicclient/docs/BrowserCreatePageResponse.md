# BrowserCreatePageResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**projection** | [**BrowserProjectionResponse**](BrowserProjectionResponse.md) |  | 
**page** | [**BrowserPageResponse**](BrowserPageResponse.md) |  | 

## Example

```python
from azentspublicclient.models.browser_create_page_response import BrowserCreatePageResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserCreatePageResponse from a JSON string
browser_create_page_response_instance = BrowserCreatePageResponse.from_json(json)
# print the JSON string representation of the object
print(BrowserCreatePageResponse.to_json())

# convert the object into a dict
browser_create_page_response_dict = browser_create_page_response_instance.to_dict()
# create an instance of BrowserCreatePageResponse from a dict
browser_create_page_response_from_dict = BrowserCreatePageResponse.from_dict(browser_create_page_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


