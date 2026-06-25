# azentspublicclient.GitHubPATV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**github_pat_v1_delete_pat**](GitHubPATV1Api.md#github_pat_v1_delete_pat) | **DELETE** /github-pat/v1/workspaces/{handle}/github-pat | Delete Pat
[**github_pat_v1_get_pat_status**](GitHubPATV1Api.md#github_pat_v1_get_pat_status) | **GET** /github-pat/v1/workspaces/{handle}/github-pat | Get Pat Status
[**github_pat_v1_get_setup_status**](GitHubPATV1Api.md#github_pat_v1_get_setup_status) | **GET** /github-pat/v1/workspaces/{handle}/github-pat/setup-status | Get Setup Status
[**github_pat_v1_register_pat**](GitHubPATV1Api.md#github_pat_v1_register_pat) | **POST** /github-pat/v1/workspaces/{handle}/github-pat | Register Pat


# **github_pat_v1_delete_pat**
> github_pat_v1_delete_pat(handle)

Delete Pat

Delete a GitHub PAT.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
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
    api_instance = azentspublicclient.GitHubPATV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Delete Pat
        api_instance.github_pat_v1_delete_pat(handle)
    except Exception as e:
        print("Exception when calling GitHubPATV1Api->github_pat_v1_delete_pat: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

void (empty response body)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**204** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **github_pat_v1_get_pat_status**
> PATStatusResponse github_pat_v1_get_pat_status(handle)

Get Pat Status

Get GitHub PAT status.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.pat_status_response import PATStatusResponse
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
    api_instance = azentspublicclient.GitHubPATV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Pat Status
        api_response = api_instance.github_pat_v1_get_pat_status(handle)
        print("The response of GitHubPATV1Api->github_pat_v1_get_pat_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubPATV1Api->github_pat_v1_get_pat_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**PATStatusResponse**](PATStatusResponse.md)

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

# **github_pat_v1_get_setup_status**
> SetupStatusResponse github_pat_v1_get_setup_status(handle)

Get Setup Status

Get status for the settings page.

Returns whether a PAT is registered.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.setup_status_response import SetupStatusResponse
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
    api_instance = azentspublicclient.GitHubPATV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Get Setup Status
        api_response = api_instance.github_pat_v1_get_setup_status(handle)
        print("The response of GitHubPATV1Api->github_pat_v1_get_setup_status:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubPATV1Api->github_pat_v1_get_setup_status: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**SetupStatusResponse**](SetupStatusResponse.md)

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

# **github_pat_v1_register_pat**
> RegisterPATResponse github_pat_v1_register_pat(handle, register_pat_request)

Register Pat

Register a GitHub PAT.

Validate the token with GitHub GET /user, then encrypt and store it.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.register_pat_request import RegisterPATRequest
from azentspublicclient.models.register_pat_response import RegisterPATResponse
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
    api_instance = azentspublicclient.GitHubPATV1Api(api_client)
    handle = 'handle_example' # str | 
    register_pat_request = azentspublicclient.RegisterPATRequest() # RegisterPATRequest | 

    try:
        # Register Pat
        api_response = api_instance.github_pat_v1_register_pat(handle, register_pat_request)
        print("The response of GitHubPATV1Api->github_pat_v1_register_pat:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubPATV1Api->github_pat_v1_register_pat: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **register_pat_request** | [**RegisterPATRequest**](RegisterPATRequest.md)|  | 

### Return type

[**RegisterPATResponse**](RegisterPATResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: application/json
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**201** | Successful Response |  -  |
**422** | Validation Error |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

