# azentspublicclient.GitHubSetupV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**github_setup_v1_agent_setup_app**](GitHubSetupV1Api.md#github_setup_v1_agent_setup_app) | **GET** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github/setup-app | Agent Setup App
[**github_setup_v1_agent_setup_verification**](GitHubSetupV1Api.md#github_setup_v1_agent_setup_verification) | **POST** /toolkit/v1/workspaces/{handle}/agents/{agent_id}/github/setup-verification | Agent Setup Verification
[**github_setup_v1_shared_setup_app**](GitHubSetupV1Api.md#github_setup_v1_shared_setup_app) | **GET** /toolkit/v1/workspaces/{handle}/github/setup-app | Shared Setup App
[**github_setup_v1_shared_setup_verification**](GitHubSetupV1Api.md#github_setup_v1_shared_setup_verification) | **POST** /toolkit/v1/workspaces/{handle}/github/setup-verification | Shared Setup Verification


# **github_setup_v1_agent_setup_app**
> GitHubSetupAppOutput github_setup_v1_agent_setup_app(handle, agent_id)

Agent Setup App

Observe current Platform App only within the exact Agent management scope.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_setup_app_output import GitHubSetupAppOutput
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
    api_instance = azentspublicclient.GitHubSetupV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 

    try:
        # Agent Setup App
        api_response = api_instance.github_setup_v1_agent_setup_app(handle, agent_id)
        print("The response of GitHubSetupV1Api->github_setup_v1_agent_setup_app:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubSetupV1Api->github_setup_v1_agent_setup_app: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 

### Return type

[**GitHubSetupAppOutput**](GitHubSetupAppOutput.md)

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

# **github_setup_v1_agent_setup_verification**
> GitHubSetupVerificationOutput github_setup_v1_agent_setup_verification(handle, agent_id, body)

Agent Setup Verification

Verify unsaved credentials only within this exact managed Agent.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.body import Body
from azentspublicclient.models.git_hub_setup_verification_output import GitHubSetupVerificationOutput
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
    api_instance = azentspublicclient.GitHubSetupV1Api(api_client)
    handle = 'handle_example' # str | 
    agent_id = 'agent_id_example' # str | 
    body = azentspublicclient.Body() # Body | 

    try:
        # Agent Setup Verification
        api_response = api_instance.github_setup_v1_agent_setup_verification(handle, agent_id, body)
        print("The response of GitHubSetupV1Api->github_setup_v1_agent_setup_verification:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubSetupV1Api->github_setup_v1_agent_setup_verification: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **agent_id** | **str**|  | 
 **body** | [**Body**](Body.md)|  | 

### Return type

[**GitHubSetupVerificationOutput**](GitHubSetupVerificationOutput.md)

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

# **github_setup_v1_shared_setup_app**
> GitHubSetupAppOutput github_setup_v1_shared_setup_app(handle)

Shared Setup App

Observe current Platform display metadata after exact shared admission.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.git_hub_setup_app_output import GitHubSetupAppOutput
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
    api_instance = azentspublicclient.GitHubSetupV1Api(api_client)
    handle = 'handle_example' # str | 

    try:
        # Shared Setup App
        api_response = api_instance.github_setup_v1_shared_setup_app(handle)
        print("The response of GitHubSetupV1Api->github_setup_v1_shared_setup_app:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubSetupV1Api->github_setup_v1_shared_setup_app: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 

### Return type

[**GitHubSetupAppOutput**](GitHubSetupAppOutput.md)

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

# **github_setup_v1_shared_setup_verification**
> GitHubSetupVerificationOutput github_setup_v1_shared_setup_verification(handle, body)

Shared Setup Verification

Verify unsaved execution identity without creating an executable Toolkit.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.body import Body
from azentspublicclient.models.git_hub_setup_verification_output import GitHubSetupVerificationOutput
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
    api_instance = azentspublicclient.GitHubSetupV1Api(api_client)
    handle = 'handle_example' # str | 
    body = azentspublicclient.Body() # Body | 

    try:
        # Shared Setup Verification
        api_response = api_instance.github_setup_v1_shared_setup_verification(handle, body)
        print("The response of GitHubSetupV1Api->github_setup_v1_shared_setup_verification:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling GitHubSetupV1Api->github_setup_v1_shared_setup_verification: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **handle** | **str**|  | 
 **body** | [**Body**](Body.md)|  | 

### Return type

[**GitHubSetupVerificationOutput**](GitHubSetupVerificationOutput.md)

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

