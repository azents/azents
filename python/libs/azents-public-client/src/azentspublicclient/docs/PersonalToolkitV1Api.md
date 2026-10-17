# azentspublicclient.PersonalToolkitV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**personal_toolkit_v1_create_personal_toolkit**](PersonalToolkitV1Api.md#personal_toolkit_v1_create_personal_toolkit) | **POST** /toolkit/v1/personal-toolkit-configs | Create Personal Toolkit
[**personal_toolkit_v1_delete_personal_toolkit**](PersonalToolkitV1Api.md#personal_toolkit_v1_delete_personal_toolkit) | **DELETE** /toolkit/v1/personal-toolkit-configs/{toolkit_id} | Delete Personal Toolkit
[**personal_toolkit_v1_get_agent_personal_toolkit_access**](PersonalToolkitV1Api.md#personal_toolkit_v1_get_agent_personal_toolkit_access) | **GET** /toolkit/v1/agents/{agent_id}/personal-toolkit-access | Get Agent Personal Toolkit Access
[**personal_toolkit_v1_get_personal_toolkit**](PersonalToolkitV1Api.md#personal_toolkit_v1_get_personal_toolkit) | **GET** /toolkit/v1/personal-toolkit-configs/{toolkit_id} | Get Personal Toolkit
[**personal_toolkit_v1_list_personal_toolkit_agents**](PersonalToolkitV1Api.md#personal_toolkit_v1_list_personal_toolkit_agents) | **GET** /toolkit/v1/personal-toolkit-agents | List Personal Toolkit Agents
[**personal_toolkit_v1_list_personal_toolkits**](PersonalToolkitV1Api.md#personal_toolkit_v1_list_personal_toolkits) | **GET** /toolkit/v1/personal-toolkit-configs | List Personal Toolkits
[**personal_toolkit_v1_save_agent_personal_toolkit_access**](PersonalToolkitV1Api.md#personal_toolkit_v1_save_agent_personal_toolkit_access) | **PATCH** /toolkit/v1/agents/{agent_id}/personal-toolkit-access | Save Agent Personal Toolkit Access
[**personal_toolkit_v1_save_personal_toolkit_access**](PersonalToolkitV1Api.md#personal_toolkit_v1_save_personal_toolkit_access) | **PATCH** /toolkit/v1/personal-toolkit-configs/{toolkit_id}/agent-access | Save Personal Toolkit Access
[**personal_toolkit_v1_update_personal_toolkit**](PersonalToolkitV1Api.md#personal_toolkit_v1_update_personal_toolkit) | **PATCH** /toolkit/v1/personal-toolkit-configs/{toolkit_id} | Update Personal Toolkit


# **personal_toolkit_v1_create_personal_toolkit**
> PersonalToolkitResponse personal_toolkit_v1_create_personal_toolkit(personal_toolkit_create_request)

Create Personal Toolkit

Create with common Provider validation and default dynamic All access.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_create_request import PersonalToolkitCreateRequest
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    personal_toolkit_create_request = azentspublicclient.PersonalToolkitCreateRequest() # PersonalToolkitCreateRequest | 

    try:
        # Create Personal Toolkit
        api_response = api_instance.personal_toolkit_v1_create_personal_toolkit(personal_toolkit_create_request)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_create_personal_toolkit:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_create_personal_toolkit: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **personal_toolkit_create_request** | [**PersonalToolkitCreateRequest**](PersonalToolkitCreateRequest.md)|  | 

### Return type

[**PersonalToolkitResponse**](PersonalToolkitResponse.md)

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

# **personal_toolkit_v1_delete_personal_toolkit**
> personal_toolkit_v1_delete_personal_toolkit(toolkit_id)

Delete Personal Toolkit

Delete the owned canonical connection before ordinary Provider cleanup.

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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Delete Personal Toolkit
        api_instance.personal_toolkit_v1_delete_personal_toolkit(toolkit_id)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_delete_personal_toolkit: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 

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

# **personal_toolkit_v1_get_agent_personal_toolkit_access**
> PersonalToolkitListResponse personal_toolkit_v1_get_agent_personal_toolkit_access(agent_id)

Get Agent Personal Toolkit Access

Read the account's personal choices after exact ordinary Agent access checks.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_list_response import PersonalToolkitListResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 

    try:
        # Get Agent Personal Toolkit Access
        api_response = api_instance.personal_toolkit_v1_get_agent_personal_toolkit_access(agent_id)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_get_agent_personal_toolkit_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_get_agent_personal_toolkit_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 

### Return type

[**PersonalToolkitListResponse**](PersonalToolkitListResponse.md)

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

# **personal_toolkit_v1_get_personal_toolkit**
> PersonalToolkitResponse personal_toolkit_v1_get_personal_toolkit(toolkit_id)

Get Personal Toolkit

Read exact-owner configuration and redacted Provider state.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 

    try:
        # Get Personal Toolkit
        api_response = api_instance.personal_toolkit_v1_get_personal_toolkit(toolkit_id)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_get_personal_toolkit:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_get_personal_toolkit: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 

### Return type

[**PersonalToolkitResponse**](PersonalToolkitResponse.md)

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

# **personal_toolkit_v1_list_personal_toolkit_agents**
> PersonalToolkitEligibleAgentListResponse personal_toolkit_v1_list_personal_toolkit_agents()

List Personal Toolkit Agents

Return all ordinarily accessible Agents, not a filtered replacement baseline.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_eligible_agent_list_response import PersonalToolkitEligibleAgentListResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)

    try:
        # List Personal Toolkit Agents
        api_response = api_instance.personal_toolkit_v1_list_personal_toolkit_agents()
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_list_personal_toolkit_agents:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_list_personal_toolkit_agents: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**PersonalToolkitEligibleAgentListResponse**](PersonalToolkitEligibleAgentListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_toolkit_v1_list_personal_toolkits**
> PersonalToolkitListResponse personal_toolkit_v1_list_personal_toolkits()

List Personal Toolkits

List only the authenticated active account's personal connections.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_list_response import PersonalToolkitListResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)

    try:
        # List Personal Toolkits
        api_response = api_instance.personal_toolkit_v1_list_personal_toolkits()
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_list_personal_toolkits:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_list_personal_toolkits: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**PersonalToolkitListResponse**](PersonalToolkitListResponse.md)

### Authorization

[HTTPBearer](../README.md#HTTPBearer)

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

### HTTP response details

| Status code | Description | Response headers |
|-------------|-------------|------------------|
**200** | Successful Response |  -  |

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

# **personal_toolkit_v1_save_agent_personal_toolkit_access**
> PersonalToolkitBatchResponse personal_toolkit_v1_save_agent_personal_toolkit_access(agent_id, personal_toolkit_agent_batch_request)

Save Agent Personal Toolkit Access

Commit every exact-Agent intent or none without requiring AgentAdmin.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_agent_batch_request import PersonalToolkitAgentBatchRequest
from azentspublicclient.models.personal_toolkit_batch_response import PersonalToolkitBatchResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    agent_id = 'agent_id_example' # str | 
    personal_toolkit_agent_batch_request = azentspublicclient.PersonalToolkitAgentBatchRequest() # PersonalToolkitAgentBatchRequest | 

    try:
        # Save Agent Personal Toolkit Access
        api_response = api_instance.personal_toolkit_v1_save_agent_personal_toolkit_access(agent_id, personal_toolkit_agent_batch_request)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_save_agent_personal_toolkit_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_save_agent_personal_toolkit_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **agent_id** | **str**|  | 
 **personal_toolkit_agent_batch_request** | [**PersonalToolkitAgentBatchRequest**](PersonalToolkitAgentBatchRequest.md)|  | 

### Return type

[**PersonalToolkitBatchResponse**](PersonalToolkitBatchResponse.md)

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

# **personal_toolkit_v1_save_personal_toolkit_access**
> PersonalToolkitAccessResponse personal_toolkit_v1_save_personal_toolkit_access(toolkit_id, personal_toolkit_access_request)

Save Personal Toolkit Access

Apply one connection-wide mode/delta intent with expected-mode protection.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_access_request import PersonalToolkitAccessRequest
from azentspublicclient.models.personal_toolkit_access_response import PersonalToolkitAccessResponse
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    personal_toolkit_access_request = azentspublicclient.PersonalToolkitAccessRequest() # PersonalToolkitAccessRequest | 

    try:
        # Save Personal Toolkit Access
        api_response = api_instance.personal_toolkit_v1_save_personal_toolkit_access(toolkit_id, personal_toolkit_access_request)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_save_personal_toolkit_access:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_save_personal_toolkit_access: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **personal_toolkit_access_request** | [**PersonalToolkitAccessRequest**](PersonalToolkitAccessRequest.md)|  | 

### Return type

[**PersonalToolkitAccessResponse**](PersonalToolkitAccessResponse.md)

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

# **personal_toolkit_v1_update_personal_toolkit**
> PersonalToolkitResponse personal_toolkit_v1_update_personal_toolkit(toolkit_id, toolkit_config_update_request)

Update Personal Toolkit

Update common settings without replacing the connection's saved access policy.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentspublicclient
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse
from azentspublicclient.models.toolkit_config_update_request import ToolkitConfigUpdateRequest
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
    api_instance = azentspublicclient.PersonalToolkitV1Api(api_client)
    toolkit_id = 'toolkit_id_example' # str | 
    toolkit_config_update_request = azentspublicclient.ToolkitConfigUpdateRequest() # ToolkitConfigUpdateRequest | 

    try:
        # Update Personal Toolkit
        api_response = api_instance.personal_toolkit_v1_update_personal_toolkit(toolkit_id, toolkit_config_update_request)
        print("The response of PersonalToolkitV1Api->personal_toolkit_v1_update_personal_toolkit:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling PersonalToolkitV1Api->personal_toolkit_v1_update_personal_toolkit: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **toolkit_id** | **str**|  | 
 **toolkit_config_update_request** | [**ToolkitConfigUpdateRequest**](ToolkitConfigUpdateRequest.md)|  | 

### Return type

[**PersonalToolkitResponse**](PersonalToolkitResponse.md)

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

