# azentsadminclient.RuntimeExecutionV1Api

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**runtime_execution_v1_create_profile**](RuntimeExecutionV1Api.md#runtime_execution_v1_create_profile) | **POST** /runtime-execution/v1/profiles | Create Profile
[**runtime_execution_v1_get_platform_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_get_platform_policy) | **GET** /runtime-execution/v1/platform-policy | Get Platform Policy
[**runtime_execution_v1_get_profile**](RuntimeExecutionV1Api.md#runtime_execution_v1_get_profile) | **GET** /runtime-execution/v1/profiles/{profile_id} | Get Profile
[**runtime_execution_v1_list_audit_events**](RuntimeExecutionV1Api.md#runtime_execution_v1_list_audit_events) | **GET** /runtime-execution/v1/audit-events | List Audit Events
[**runtime_execution_v1_list_profiles**](RuntimeExecutionV1Api.md#runtime_execution_v1_list_profiles) | **GET** /runtime-execution/v1/profiles | List Profiles
[**runtime_execution_v1_replace_platform_policy**](RuntimeExecutionV1Api.md#runtime_execution_v1_replace_platform_policy) | **PUT** /runtime-execution/v1/platform-policy | Replace Platform Policy
[**runtime_execution_v1_replace_profile**](RuntimeExecutionV1Api.md#runtime_execution_v1_replace_profile) | **PUT** /runtime-execution/v1/profiles/{profile_id} | Replace Profile
[**runtime_execution_v1_retire_profile**](RuntimeExecutionV1Api.md#runtime_execution_v1_retire_profile) | **POST** /runtime-execution/v1/profiles/{profile_id}/retire | Retire Profile


# **runtime_execution_v1_create_profile**
> RuntimeExecutionProfileResponse runtime_execution_v1_create_profile(runtime_execution_profile_create_request)

Create Profile

Create one ordinary active execution Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_profile_create_request import RuntimeExecutionProfileCreateRequest
from azentsadminclient.models.runtime_execution_profile_response import RuntimeExecutionProfileResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    runtime_execution_profile_create_request = azentsadminclient.RuntimeExecutionProfileCreateRequest() # RuntimeExecutionProfileCreateRequest | 

    try:
        # Create Profile
        api_response = api_instance.runtime_execution_v1_create_profile(runtime_execution_profile_create_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_create_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_create_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_execution_profile_create_request** | [**RuntimeExecutionProfileCreateRequest**](RuntimeExecutionProfileCreateRequest.md)|  | 

### Return type

[**RuntimeExecutionProfileResponse**](RuntimeExecutionProfileResponse.md)

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

# **runtime_execution_v1_get_platform_policy**
> RuntimeExecutionPlatformPolicyResponse runtime_execution_v1_get_platform_policy()

Get Platform Policy

Return the installation-wide execution-policy ceiling.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_platform_policy_response import RuntimeExecutionPlatformPolicyResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)

    try:
        # Get Platform Policy
        api_response = api_instance.runtime_execution_v1_get_platform_policy()
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_get_platform_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_get_platform_policy: %s\n" % e)
```



### Parameters

This endpoint does not need any parameter.

### Return type

[**RuntimeExecutionPlatformPolicyResponse**](RuntimeExecutionPlatformPolicyResponse.md)

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

# **runtime_execution_v1_get_profile**
> RuntimeExecutionProfileResponse runtime_execution_v1_get_profile(profile_id)

Get Profile

Return one stable execution Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_profile_response import RuntimeExecutionProfileResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    profile_id = 'profile_id_example' # str | 

    try:
        # Get Profile
        api_response = api_instance.runtime_execution_v1_get_profile(profile_id)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_get_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_get_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 

### Return type

[**RuntimeExecutionProfileResponse**](RuntimeExecutionProfileResponse.md)

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

# **runtime_execution_v1_list_audit_events**
> RuntimeExecutionPolicyAuditListResponse runtime_execution_v1_list_audit_events(management_layer=management_layer, target_id=target_id, workspace_id=workspace_id, agent_id=agent_id, offset=offset, limit=limit)

List Audit Events

List metadata-only execution-policy audit history.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_management_layer import RuntimeExecutionManagementLayer
from azentsadminclient.models.runtime_execution_policy_audit_list_response import RuntimeExecutionPolicyAuditListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    management_layer = azentsadminclient.RuntimeExecutionManagementLayer() # RuntimeExecutionManagementLayer |  (optional)
    target_id = 'target_id_example' # str |  (optional)
    workspace_id = 'workspace_id_example' # str |  (optional)
    agent_id = 'agent_id_example' # str |  (optional)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Audit Events
        api_response = api_instance.runtime_execution_v1_list_audit_events(management_layer=management_layer, target_id=target_id, workspace_id=workspace_id, agent_id=agent_id, offset=offset, limit=limit)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_list_audit_events:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_list_audit_events: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **management_layer** | [**RuntimeExecutionManagementLayer**](.md)|  | [optional] 
 **target_id** | **str**|  | [optional] 
 **workspace_id** | **str**|  | [optional] 
 **agent_id** | **str**|  | [optional] 
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeExecutionPolicyAuditListResponse**](RuntimeExecutionPolicyAuditListResponse.md)

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

# **runtime_execution_v1_list_profiles**
> RuntimeExecutionProfileListResponse runtime_execution_v1_list_profiles(include_retired=include_retired, offset=offset, limit=limit)

List Profiles

List stable execution Profiles.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_profile_list_response import RuntimeExecutionProfileListResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    include_retired = False # bool |  (optional) (default to False)
    offset = 0 # int |  (optional) (default to 0)
    limit = 50 # int |  (optional) (default to 50)

    try:
        # List Profiles
        api_response = api_instance.runtime_execution_v1_list_profiles(include_retired=include_retired, offset=offset, limit=limit)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_list_profiles:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_list_profiles: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **include_retired** | **bool**|  | [optional] [default to False]
 **offset** | **int**|  | [optional] [default to 0]
 **limit** | **int**|  | [optional] [default to 50]

### Return type

[**RuntimeExecutionProfileListResponse**](RuntimeExecutionProfileListResponse.md)

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

# **runtime_execution_v1_replace_platform_policy**
> RuntimeExecutionPlatformPolicyResponse runtime_execution_v1_replace_platform_policy(runtime_execution_platform_policy_replace_request)

Replace Platform Policy

Replace the Platform execution-policy ceiling.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_platform_policy_replace_request import RuntimeExecutionPlatformPolicyReplaceRequest
from azentsadminclient.models.runtime_execution_platform_policy_response import RuntimeExecutionPlatformPolicyResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    runtime_execution_platform_policy_replace_request = azentsadminclient.RuntimeExecutionPlatformPolicyReplaceRequest() # RuntimeExecutionPlatformPolicyReplaceRequest | 

    try:
        # Replace Platform Policy
        api_response = api_instance.runtime_execution_v1_replace_platform_policy(runtime_execution_platform_policy_replace_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_replace_platform_policy:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_replace_platform_policy: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **runtime_execution_platform_policy_replace_request** | [**RuntimeExecutionPlatformPolicyReplaceRequest**](RuntimeExecutionPlatformPolicyReplaceRequest.md)|  | 

### Return type

[**RuntimeExecutionPlatformPolicyResponse**](RuntimeExecutionPlatformPolicyResponse.md)

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

# **runtime_execution_v1_replace_profile**
> RuntimeExecutionProfileResponse runtime_execution_v1_replace_profile(profile_id, runtime_execution_profile_replace_request)

Replace Profile

Replace Profile metadata and policy content.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_profile_replace_request import RuntimeExecutionProfileReplaceRequest
from azentsadminclient.models.runtime_execution_profile_response import RuntimeExecutionProfileResponse
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    runtime_execution_profile_replace_request = azentsadminclient.RuntimeExecutionProfileReplaceRequest() # RuntimeExecutionProfileReplaceRequest | 

    try:
        # Replace Profile
        api_response = api_instance.runtime_execution_v1_replace_profile(profile_id, runtime_execution_profile_replace_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_replace_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_replace_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **runtime_execution_profile_replace_request** | [**RuntimeExecutionProfileReplaceRequest**](RuntimeExecutionProfileReplaceRequest.md)|  | 

### Return type

[**RuntimeExecutionProfileResponse**](RuntimeExecutionProfileResponse.md)

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

# **runtime_execution_v1_retire_profile**
> RuntimeExecutionProfileResponse runtime_execution_v1_retire_profile(profile_id, runtime_execution_profile_retire_request)

Retire Profile

Retire one ordinary Profile.

### Example

* Bearer Authentication (HTTPBearer):

```python
import azentsadminclient
from azentsadminclient.models.runtime_execution_profile_response import RuntimeExecutionProfileResponse
from azentsadminclient.models.runtime_execution_profile_retire_request import RuntimeExecutionProfileRetireRequest
from azentsadminclient.rest import ApiException
from pprint import pprint

# Defining the host is optional and defaults to http://localhost
# See configuration.py for a list of all supported configuration parameters.
configuration = azentsadminclient.Configuration(
    host = "http://localhost"
)

# The client must configure the authentication and authorization parameters
# in accordance with the API server security policy.
# Examples for each auth method are provided below, use the example that
# satisfies your auth use case.

# Configure Bearer authorization: HTTPBearer
configuration = azentsadminclient.Configuration(
    access_token = os.environ["BEARER_TOKEN"]
)

# Enter a context with an instance of the API client
with azentsadminclient.ApiClient(configuration) as api_client:
    # Create an instance of the API class
    api_instance = azentsadminclient.RuntimeExecutionV1Api(api_client)
    profile_id = 'profile_id_example' # str | 
    runtime_execution_profile_retire_request = azentsadminclient.RuntimeExecutionProfileRetireRequest() # RuntimeExecutionProfileRetireRequest | 

    try:
        # Retire Profile
        api_response = api_instance.runtime_execution_v1_retire_profile(profile_id, runtime_execution_profile_retire_request)
        print("The response of RuntimeExecutionV1Api->runtime_execution_v1_retire_profile:\n")
        pprint(api_response)
    except Exception as e:
        print("Exception when calling RuntimeExecutionV1Api->runtime_execution_v1_retire_profile: %s\n" % e)
```



### Parameters


Name | Type | Description  | Notes
------------- | ------------- | ------------- | -------------
 **profile_id** | **str**|  | 
 **runtime_execution_profile_retire_request** | [**RuntimeExecutionProfileRetireRequest**](RuntimeExecutionProfileRetireRequest.md)|  | 

### Return type

[**RuntimeExecutionProfileResponse**](RuntimeExecutionProfileResponse.md)

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

