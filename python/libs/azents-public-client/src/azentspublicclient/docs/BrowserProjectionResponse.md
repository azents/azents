# BrowserProjectionResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**available** | **bool** |  | 
**reason_code** | [**RuntimeBrowserReasonCode**](RuntimeBrowserReasonCode.md) |  | 
**allow_input** | **bool** |  | 
**tasks** | [**List[BrowserTaskResponse]**](BrowserTaskResponse.md) |  | 

## Example

```python
from azentspublicclient.models.browser_projection_response import BrowserProjectionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of BrowserProjectionResponse from a JSON string
browser_projection_response_instance = BrowserProjectionResponse.from_json(json)
# print the JSON string representation of the object
print(BrowserProjectionResponse.to_json())

# convert the object into a dict
browser_projection_response_dict = browser_projection_response_instance.to_dict()
# create an instance of BrowserProjectionResponse from a dict
browser_projection_response_from_dict = BrowserProjectionResponse.from_dict(browser_projection_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


