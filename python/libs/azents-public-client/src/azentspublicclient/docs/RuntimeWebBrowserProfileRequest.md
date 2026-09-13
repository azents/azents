# RuntimeWebBrowserProfileRequest

Trusted Main Web proof for the admitted browser profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**browser_profile** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_browser_profile_request import RuntimeWebBrowserProfileRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebBrowserProfileRequest from a JSON string
runtime_web_browser_profile_request_instance = RuntimeWebBrowserProfileRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebBrowserProfileRequest.to_json())

# convert the object into a dict
runtime_web_browser_profile_request_dict = runtime_web_browser_profile_request_instance.to_dict()
# create an instance of RuntimeWebBrowserProfileRequest from a dict
runtime_web_browser_profile_request_from_dict = RuntimeWebBrowserProfileRequest.from_dict(runtime_web_browser_profile_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


