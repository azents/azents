# azentspublicclient.WorkspaceModelSettingsV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**workspace_model_settings_v1_get_workspace_model_settings**](WorkspaceModelSettingsV1Api.md#workspace_model_settings_v1_get_workspace_model_settings) | **GET** /workspace-model-settings/v1/workspaces/{handle} | Get Workspace Model Settings
[**workspace_model_settings_v1_update_workspace_model_settings**](WorkspaceModelSettingsV1Api.md#workspace_model_settings_v1_update_workspace_model_settings) | **PUT** /workspace-model-settings/v1/workspaces/{handle} | Update Workspace Model Settings


# **workspace_model_settings_v1_get_workspace_model_settings**
> WorkspaceModelSettingsResponse workspace_model_settings_v1_get_workspace_model_settings(handle)

Get Workspace Model Settings

Get the workspace default model settings.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_model_settings_response import WorkspaceModelSettingsResponse
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.WorkspaceModelSettingsV1Api(api_client)
    handle = 'handle_example' # str |

    try:
        # Get Workspace Model Settings
        api_response = api_instance.workspace_model_settings_v1_get_workspace_model_settings(handle)
        print("The response of WorkspaceModelSettingsV1Api->workspace_model_settings_v1_get_workspace_model_settings:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceModelSettingsV1Api->workspace_model_settings_v1_get_workspace_model_settings: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |

### Return type

[**WorkspaceModelSettingsResponse**](WorkspaceModelSettingsResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **workspace_model_settings_v1_update_workspace_model_settings**
> WorkspaceModelSettingsResponse workspace_model_settings_v1_update_workspace_model_settings(handle, workspace_model_settings_update_request)

Update Workspace Model Settings

Update the workspace default model settings.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.workspace_model_settings_response import WorkspaceModelSettingsResponse
from azentspublicclient.models.workspace_model_settings_update_request import WorkspaceModelSettingsUpdateRequest
from azentspublicclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentspublicclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentspublicclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentspublicclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentspublicclient.WorkspaceModelSettingsV1Api(api_client)
    handle = 'handle_example' # str |
    workspace_model_settings_update_request = azentspublicclient.WorkspaceModelSettingsUpdateRequest() # WorkspaceModelSettingsUpdateRequest |

    try:
        # Update Workspace Model Settings
        api_response = api_instance.workspace_model_settings_v1_update_workspace_model_settings(handle, workspace_model_settings_update_request)
        print("The response of WorkspaceModelSettingsV1Api->workspace_model_settings_v1_update_workspace_model_settings:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling WorkspaceModelSettingsV1Api->workspace_model_settings_v1_update_workspace_model_settings: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  |
 **workspace_model_settings_update_request** | [**WorkspaceModelSettingsUpdateRequest**](WorkspaceModelSettingsUpdateRequest.md)|  |

### Return type

[**WorkspaceModelSettingsResponse**](WorkspaceModelSettingsResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

