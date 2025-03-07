cmake_minimum_required(VERSION 3.3)

foreach(policy
        CMP0023
        CMP0048 # CMake 3.0
        CMP0074 # CMake 3.12
        CMP0077
        CMP0079
    )
    if(POLICY ${policy})
        cmake_policy(SET ${policy} NEW)
    endif()
endforeach()

# set default policy
foreach(default_policy_var_name
        # make option() honor normal variables for BUILD_SHARED_LIBS:
        # - re2
        # - snappy
        CMAKE_POLICY_DEFAULT_CMP0077
        # Google Test from sources uses too old cmake, 2.6.x, and CMP0022 should
        # set, to avoid using deprecated LINK_INTERFACE_LIBRARIES(_<CONFIG>)? over
        # INTERFACE_LINK_LIBRARIES.
        CMAKE_POLICY_DEFAULT_CMP0022
    )
    set(${default_policy_var_name} NEW)
endforeach()

project(ClickHouse)

# If turned off: e.g. when ENABLE_FOO is ON, but FOO tool was not found, the CMake will continue.
option(FAIL_ON_UNSUPPORTED_OPTIONS_COMBINATION
   "Stop/Fail CMake configuration if some ENABLE_XXX option is defined (either ON or OFF)
   but is not possible to satisfy" ON)

if(FAIL_ON_UNSUPPORTED_OPTIONS_COMBINATION)
    set(RECONFIGURE_MESSAGE_LEVEL FATAL_ERROR)
else()
    set(RECONFIGURE_MESSAGE_LEVEL WARNING)
endif()

enable_language(C CXX ASM)

include (cmake/arch.cmake)
include (cmake/target.cmake)
include (cmake/tools.cmake)
include (cmake/analysis.cmake)
include (cmake/git_status.cmake)

# Ignore export() since we don't use it,
# but it gets broken with a global targets via link_libraries()
macro (export)
endmacro ()

set(CMAKE_MODULE_PATH ${CMAKE_MODULE_PATH} "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Modules/")
set(CMAKE_EXPORT_COMPILE_COMMANDS 1) # Write compile_commands.json
set(CMAKE_LINK_DEPENDS_NO_SHARED 1) # Do not relink all depended targets on .so
set(CMAKE_CONFIGURATION_TYPES "RelWithDebInfo;Debug;Release;MinSizeRel" CACHE STRING "" FORCE)
set(CMAKE_DEBUG_POSTFIX "d" CACHE STRING "Generate debug library name with a postfix.")    # To be consistent with CMakeLists from contrib libs.

# Enable the ability to organize targets into hierarchies of "folders" for capable GUI-based IDEs.
# For more info see https://cmake.org/cmake/help/latest/prop_gbl/USE_FOLDERS.html
set_property(GLOBAL PROPERTY USE_FOLDERS ON)

# Check that submodules are present only if source was downloaded with git
if (EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/.git" AND NOT EXISTS "${ClickHouse_SOURCE_DIR}/contrib/boost/boost")
    message (FATAL_ERROR "Submodules are not initialized. Run\n\tgit submodule update --init --recursive")
endif ()

include (cmake/find/ccache.cmake)

# Take care to add prlimit in command line before ccache, or else ccache thinks that
# prlimit is compiler, and clang++ is its input file, and refuses to work  with
# multiple inputs, e.g in ccache log:
# [2021-03-31T18:06:32.655327 36900] Command line: /usr/bin/ccache prlimit --as=10000000000 --data=5000000000 --cpu=600 /usr/bin/clang++-11 - ...... std=gnu++2a -MD -MT src/CMakeFiles/dbms.dir/Storages/MergeTree/IMergeTreeDataPart.cpp.o -MF src/CMakeFiles/dbms.dir/Storages/MergeTree/IMergeTreeDataPart.cpp.o.d -o src/CMakeFiles/dbms.dir/Storages/MergeTree/IMergeTreeDataPart.cpp.o -c ../src/Storages/MergeTree/IMergeTreeDataPart.cpp
#
# [2021-03-31T18:06:32.656704 36900] Multiple input files: /usr/bin/clang++-11 and ../src/Storages/MergeTree/IMergeTreeDataPart.cpp
#
# Another way would be to use --ccache-skip option before clang++-11 to make
# ccache ignore it.
option(ENABLE_CHECK_HEAVY_BUILDS "Don't allow C++ translation units to compile too long or to take too much memory while compiling." OFF)
if (ENABLE_CHECK_HEAVY_BUILDS)
    # set DATA (since RSS does not work since 2.6.x+) to 2G
    set (RLIMIT_DATA 5000000000)
    # set VIRT (RLIMIT_AS) to 10G (DATA*10)
    set (RLIMIT_AS 10000000000)
    # set CPU time limit to 600 seconds
    set (RLIMIT_CPU 600)

    # gcc10/gcc10/clang -fsanitize=memory is too heavy
    if (SANITIZE STREQUAL "memory" OR COMPILER_GCC)
       set (RLIMIT_DATA 10000000000)
    endif()

    set (CMAKE_CXX_COMPILER_LAUNCHER prlimit --as=${RLIMIT_AS} --data=${RLIMIT_DATA} --cpu=${RLIMIT_CPU} ${CMAKE_CXX_COMPILER_LAUNCHER})
endif ()

if (NOT CMAKE_BUILD_TYPE OR CMAKE_BUILD_TYPE STREQUAL "None")
    set (CMAKE_BUILD_TYPE "RelWithDebInfo")
    message (STATUS "CMAKE_BUILD_TYPE is not set, set to default = ${CMAKE_BUILD_TYPE}")
endif ()
message (STATUS "CMAKE_BUILD_TYPE: ${CMAKE_BUILD_TYPE}")

string (TOUPPER ${CMAKE_BUILD_TYPE} CMAKE_BUILD_TYPE_UC)

option(USE_STATIC_LIBRARIES "Disable to use shared libraries" ON)
option(MAKE_STATIC_LIBRARIES "Disable to make shared libraries" ${USE_STATIC_LIBRARIES})

if (NOT MAKE_STATIC_LIBRARIES)
    # DEVELOPER ONLY.
    # Faster linking if turned on.
    option(SPLIT_SHARED_LIBRARIES "Keep all internal libraries as separate .so files")

    option(CLICKHOUSE_SPLIT_BINARY
        "Make several binaries (clickhouse-server, clickhouse-client etc.) instead of one bundled")
endif ()

if (MAKE_STATIC_LIBRARIES AND SPLIT_SHARED_LIBRARIES)
    message(FATAL_ERROR "Defining SPLIT_SHARED_LIBRARIES=1 without MAKE_STATIC_LIBRARIES=0 has no effect.")
endif()

if (NOT MAKE_STATIC_LIBRARIES AND SPLIT_SHARED_LIBRARIES)
    set(BUILD_SHARED_LIBS 1 CACHE INTERNAL "")
endif ()

if (USE_STATIC_LIBRARIES)
    list(REVERSE CMAKE_FIND_LIBRARY_SUFFIXES)
endif ()

option (ENABLE_FUZZING "Fuzzy testing using libfuzzer" OFF)

if (ENABLE_FUZZING)
    # Also set WITH_COVERAGE=1 for better fuzzing process
    # By default this is disabled, because fuzzers are built in CI with the clickhouse itself.
    # And we don't want to enable coverage for it.
    message (STATUS "Fuzzing instrumentation enabled")
    set (FUZZER "libfuzzer")
endif()

# Global libraries
# See:
# - default_libs.cmake
# - sanitize.cmake
add_library(global-libs INTERFACE)

include (cmake/fuzzer.cmake)
include (cmake/sanitize.cmake)

if (CMAKE_GENERATOR STREQUAL "Ninja" AND NOT DISABLE_COLORED_BUILD)
    # Turn on colored output. https://github.com/ninja-build/ninja/wiki/FAQ
    set (CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fdiagnostics-color=always")
    set (CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fdiagnostics-color=always")
endif ()

include (cmake/add_warning.cmake)

if (NOT MSVC)
    set (COMMON_WARNING_FLAGS "${COMMON_WARNING_FLAGS} -Wall")    # -Werror and many more is also added inside cmake/warnings.cmake
endif ()

if (COMPILER_CLANG)
    # clang: warning: argument unused during compilation: '-specs=/usr/share/dpkg/no-pie-compile.specs' [-Wunused-command-line-argument]
    set (COMMON_WARNING_FLAGS "${COMMON_WARNING_FLAGS} -Wno-unused-command-line-argument")
    # generate ranges for fast "addr2line" search
    if (NOT CMAKE_BUILD_TYPE_UC STREQUAL "RELEASE")
        set(COMPILER_FLAGS "${COMPILER_FLAGS} -gdwarf-aranges")
    endif ()

    if (CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL 12.0.0)
		if (CMAKE_BUILD_TYPE_UC STREQUAL "DEBUG" OR CMAKE_BUILD_TYPE_UC STREQUAL "RELWITHDEBINFO")
            set (CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -Xclang -fuse-ctor-homing")
            set (CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Xclang -fuse-ctor-homing")
        endif()
    endif()
endif ()

# If turned `ON`, assumes the user has either the system GTest library or the bundled one.
option(ENABLE_TESTS "Provide unit_test_dbms target with Google.Test unit tests" ON)
option(ENABLE_EXAMPLES "Build all example programs in 'examples' subdirectories" OFF)

if (OS_LINUX AND (ARCH_AMD64 OR ARCH_AARCH64) AND NOT UNBUNDLED AND MAKE_STATIC_LIBRARIES AND NOT SPLIT_SHARED_LIBRARIES AND CMAKE_VERSION VERSION_GREATER "3.9.0")
    # Only for Linux, x86_64 or aarch64.
    option(GLIBC_COMPATIBILITY "Enable compatibility with older glibc libraries." ON)
elseif(GLIBC_COMPATIBILITY)
    message (${RECONFIGURE_MESSAGE_LEVEL} "Glibc compatibility cannot be enabled in current configuration")
endif ()

if (NOT CMAKE_VERSION VERSION_GREATER "3.9.0")
    message (WARNING "CMake version must be greater than 3.9.0 for production builds.")
endif ()

# Make sure the final executable has symbols exported
set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -rdynamic")

find_program (OBJCOPY_PATH NAMES "llvm-objcopy" "llvm-objcopy-12" "llvm-objcopy-11" "llvm-objcopy-10" "llvm-objcopy-9" "llvm-objcopy-8" "objcopy")

if (NOT OBJCOPY_PATH AND OS_DARWIN)
    find_program (BREW_PATH NAMES "brew")
    if (BREW_PATH)
        execute_process (COMMAND ${BREW_PATH} --prefix llvm ERROR_QUIET OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE LLVM_PREFIX)
        if (LLVM_PREFIX)
            find_program (OBJCOPY_PATH NAMES "llvm-objcopy" PATHS "${LLVM_PREFIX}/bin" NO_DEFAULT_PATH)
        endif ()
        if (NOT OBJCOPY_PATH)
            execute_process (COMMAND ${BREW_PATH} --prefix binutils ERROR_QUIET OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE BINUTILS_PREFIX)
            if (BINUTILS_PREFIX)
                find_program (OBJCOPY_PATH NAMES "objcopy" PATHS "${BINUTILS_PREFIX}/bin" NO_DEFAULT_PATH)
            endif ()
        endif ()
    endif ()
endif ()

if (OBJCOPY_PATH)
    message (STATUS "Using objcopy: ${OBJCOPY_PATH}")
else ()
    message (FATAL_ERROR "Cannot find objcopy.")
endif ()

if (OS_DARWIN)
    # The `-all_load` flag forces loading of all symbols from all libraries,
    # and leads to multiply-defined symbols. This flag allows force loading
    # from a _specific_ library, which is what we need.
    set(WHOLE_ARCHIVE -force_load)
    # The `-noall_load` flag is the default and now obsolete.
    set(NO_WHOLE_ARCHIVE "")
else ()
    set(WHOLE_ARCHIVE --whole-archive)
    set(NO_WHOLE_ARCHIVE --no-whole-archive)
endif ()

# Ignored if `lld` is used
option(ADD_GDB_INDEX_FOR_GOLD "Add .gdb-index to resulting binaries for gold linker.")

if (NOT CMAKE_BUILD_TYPE_UC STREQUAL "RELEASE")
    # Can be lld or ld-lld.
    if (LINKER_NAME MATCHES "lld$")
        set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--gdb-index")
        set (CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -Wl,--gdb-index")
        message (STATUS "Adding .gdb-index via --gdb-index linker option.")
    # we use another tool for gdb-index, because gold linker removes section .debug_aranges, which used inside clickhouse stacktraces
    # http://sourceware-org.1504.n7.nabble.com/gold-No-debug-aranges-section-when-linking-with-gdb-index-td540965.html#a556932
    elseif (LINKER_NAME MATCHES "gold$" AND ADD_GDB_INDEX_FOR_GOLD)
        find_program (GDB_ADD_INDEX_EXE NAMES "gdb-add-index" DOC "Path to gdb-add-index executable")
        if (NOT GDB_ADD_INDEX_EXE)
            set (USE_GDB_ADD_INDEX 0)
            message (WARNING "Cannot add gdb index to binaries, because gold linker is used, but gdb-add-index executable not found.")
        else()
            set (USE_GDB_ADD_INDEX 1)
            message (STATUS "gdb-add-index found: ${GDB_ADD_INDEX_EXE}")
        endif()
    endif ()
endif()

# Create BuildID when using lld. For other linkers it is created by default.
if (LINKER_NAME MATCHES "lld$")
    # SHA1 is not cryptographically secure but it is the best what lld is offering.
    set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--build-id=sha1")
endif ()

# Add a section with the hash of the compiled machine code for integrity checks.
# Only for official builds, because adding a section can be time consuming (rewrite of several GB).
# And cross compiled binaries are not supported (since you cannot execute clickhouse hash-binary)
if (OBJCOPY_PATH AND YANDEX_OFFICIAL_BUILD AND (NOT CMAKE_TOOLCHAIN_FILE))
    set (USE_BINARY_HASH 1)
endif ()

cmake_host_system_information(RESULT AVAILABLE_PHYSICAL_MEMORY QUERY AVAILABLE_PHYSICAL_MEMORY) # Not available under freebsd


if(NOT AVAILABLE_PHYSICAL_MEMORY OR AVAILABLE_PHYSICAL_MEMORY GREATER 8000)
    # Less `/tmp` usage, more RAM usage.
    option(COMPILER_PIPE "-pipe compiler option" ON)
endif()

if(COMPILER_PIPE)
    set(COMPILER_FLAGS "${COMPILER_FLAGS} -pipe")
else()
    message(STATUS "Disabling compiler -pipe option (have only ${AVAILABLE_PHYSICAL_MEMORY} mb of memory)")
endif()

include(cmake/cpu_features.cmake)

# Asynchronous unwind tables are needed for Query Profiler.
# They are already by default on some platforms but possibly not on all platforms.
# Enable it explicitly.
set (COMPILER_FLAGS "${COMPILER_FLAGS} -fasynchronous-unwind-tables")

if (${CMAKE_VERSION} VERSION_LESS "3.12.4")
    # CMake < 3.12 doesn't support setting 20 as a C++ standard version.
    # We will add C++ standard controlling flag in CMAKE_CXX_FLAGS manually for now.

    if (COMPILER_GCC OR COMPILER_CLANG)
        # to make numeric_limits<__int128> works with GCC
        set (_CXX_STANDARD "gnu++2a")
    else ()
        set (_CXX_STANDARD "c++2a")
    endif ()

    set (CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=${_CXX_STANDARD}")
else ()
    set (CMAKE_CXX_STANDARD 20)
    set (CMAKE_CXX_EXTENSIONS ON) # Same as gnu++2a (ON) vs c++2a (OFF): https://cmake.org/cmake/help/latest/prop_tgt/CXX_EXTENSIONS.html
    set (CMAKE_CXX_STANDARD_REQUIRED ON)
endif ()

set (CMAKE_C_STANDARD 11)
set (CMAKE_C_EXTENSIONS ON)
set (CMAKE_C_STANDARD_REQUIRED ON)

if (COMPILER_GCC OR COMPILER_CLANG)
    # Enable C++14 sized global deallocation functions. It should be enabled by setting -std=c++14 but I'm not sure.
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fsized-deallocation")
endif ()

# falign-functions=32 prevents from random performance regressions with the code change. Thus, providing more stable
# benchmarks.
if (COMPILER_GCC OR COMPILER_CLANG)
    set(COMPILER_FLAGS "${COMPILER_FLAGS} -falign-functions=32")
endif ()

# Compiler-specific coverage flags e.g. -fcoverage-mapping for gcc
option(WITH_COVERAGE "Profile the resulting binary/binaries" OFF)

if (WITH_COVERAGE AND COMPILER_CLANG)
    set(COMPILER_FLAGS "${COMPILER_FLAGS} -fprofile-instr-generate -fcoverage-mapping")
    # If we want to disable coverage for specific translation units
    set(WITHOUT_COVERAGE "-fno-profile-instr-generate -fno-coverage-mapping")
endif()

if (WITH_COVERAGE AND COMPILER_GCC)
    set(COMPILER_FLAGS "${COMPILER_FLAGS} -fprofile-arcs -ftest-coverage")
    set(COVERAGE_OPTION "-lgcov")
    set(WITHOUT_COVERAGE "-fno-profile-arcs -fno-test-coverage")
endif()

set(COMPILER_FLAGS "${COMPILER_FLAGS}")

set (CMAKE_BUILD_COLOR_MAKEFILE          ON)
set (CMAKE_CXX_FLAGS                     "${CMAKE_CXX_FLAGS} ${COMPILER_FLAGS} ${PLATFORM_EXTRA_CXX_FLAG} ${COMMON_WARNING_FLAGS} ${CXX_WARNING_FLAGS}")
set (CMAKE_CXX_FLAGS_RELWITHDEBINFO      "${CMAKE_CXX_FLAGS_RELWITHDEBINFO} -O3 ${CMAKE_CXX_FLAGS_ADD}")
set (CMAKE_CXX_FLAGS_DEBUG               "${CMAKE_CXX_FLAGS_DEBUG} -O0 -g3 -ggdb3 -fno-inline ${CMAKE_CXX_FLAGS_ADD}")

set (CMAKE_C_FLAGS                       "${CMAKE_C_FLAGS} ${COMPILER_FLAGS} ${COMMON_WARNING_FLAGS} ${CMAKE_C_FLAGS_ADD}")
set (CMAKE_C_FLAGS_RELWITHDEBINFO        "${CMAKE_C_FLAGS_RELWITHDEBINFO} -O3 ${CMAKE_C_FLAGS_ADD}")
set (CMAKE_C_FLAGS_DEBUG                 "${CMAKE_C_FLAGS_DEBUG} -O0 -g3 -ggdb3 -fno-inline ${CMAKE_C_FLAGS_ADD}")

if (COMPILER_CLANG)
    if (OS_DARWIN)
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -stdlib=libc++")
        set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,-U,_inside_main")
    endif()

    # Display absolute paths in error messages. Otherwise KDevelop fails to navigate to correct file and opens a new file instead.
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fdiagnostics-absolute-paths")
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fdiagnostics-absolute-paths")

    if (NOT ENABLE_TESTS AND NOT SANITIZE)
        # https://clang.llvm.org/docs/ThinLTO.html
        # Applies to clang only.
        # Disabled when building with tests or sanitizers.
        option(ENABLE_THINLTO "Clang-specific link time optimization" ON)
    endif()

    # Set new experimental pass manager, it's a performance, build time and binary size win.
    # Can be removed after https://reviews.llvm.org/D66490 merged and released to at least two versions of clang.
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fexperimental-new-pass-manager")
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fexperimental-new-pass-manager")

    # We cannot afford to use LTO when compiling unit tests, and it's not enough
    # to only supply -fno-lto at the final linking stage. So we disable it
    # completely.
    if (ENABLE_THINLTO AND NOT ENABLE_TESTS AND NOT SANITIZE)
        # Link time optimization
        set (CMAKE_C_FLAGS_RELWITHDEBINFO "${CMAKE_C_FLAGS_RELWITHDEBINFO} -flto=thin")
        set (CMAKE_CXX_FLAGS_RELWITHDEBINFO "${CMAKE_CXX_FLAGS_RELWITHDEBINFO} -flto=thin")
        set (CMAKE_EXE_LINKER_FLAGS_RELWITHDEBINFO "${CMAKE_EXE_LINKER_FLAGS_RELWITHDEBINFO} -flto=thin")
    elseif (ENABLE_THINLTO)
        message (${RECONFIGURE_MESSAGE_LEVEL} "Cannot enable ThinLTO")
    endif ()

    # Always prefer llvm tools when using clang. For instance, we cannot use GNU ar when llvm LTO is enabled
    find_program (LLVM_AR_PATH NAMES "llvm-ar" "llvm-ar-12" "llvm-ar-11" "llvm-ar-10" "llvm-ar-9" "llvm-ar-8")

    if (LLVM_AR_PATH)
        message(STATUS "Using llvm-ar: ${LLVM_AR_PATH}.")
        set (CMAKE_AR ${LLVM_AR_PATH})
    else ()
        message(WARNING "Cannot find llvm-ar. System ar will be used instead. It does not work with ThinLTO.")
    endif ()

    find_program (LLVM_RANLIB_PATH NAMES "llvm-ranlib" "llvm-ranlib-12" "llvm-ranlib-11" "llvm-ranlib-10" "llvm-ranlib-9" "llvm-ranlib-8")

    if (LLVM_RANLIB_PATH)
        message(STATUS "Using llvm-ranlib: ${LLVM_RANLIB_PATH}.")
        set (CMAKE_RANLIB ${LLVM_RANLIB_PATH})
    else ()
        message(WARNING "Cannot find llvm-ranlib. System ranlib will be used instead. It does not work with ThinLTO.")
    endif ()

elseif (ENABLE_THINLTO)
    message (${RECONFIGURE_MESSAGE_LEVEL} "ThinLTO is only available with CLang")
endif ()

# Turns on all external libs like s3, kafka, ODBC, ...
option(ENABLE_LIBRARIES "Enable all external libraries by default" ON)

# We recommend avoiding this mode for production builds because we can't guarantee
# all needed libraries exist in your system.
# This mode exists for enthusiastic developers who are searching for trouble.
# The whole idea of using unknown version of libraries from the OS distribution is deeply flawed.
# Useful for maintainers of OS packages.
option (UNBUNDLED "Use system libraries instead of ones in contrib/" OFF)

if (UNBUNDLED)
    set(NOT_UNBUNDLED OFF)
else ()
    set(NOT_UNBUNDLED ON)
endif ()

if (UNBUNDLED OR NOT (OS_LINUX OR OS_DARWIN))
    # Using system libs can cause a lot of warnings in includes (on macro expansion).
    option(WERROR "Enable -Werror compiler option" OFF)
else ()
    option(WERROR "Enable -Werror compiler option" ON)
endif ()

if (WERROR)
    add_warning(error)
endif ()

# Make this extra-checks for correct library dependencies.
if (OS_LINUX AND NOT SANITIZE)
    set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--no-undefined")
    set (CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS} -Wl,--no-undefined")
endif ()

include(cmake/dbms_glob_sources.cmake)

if (OS_LINUX OR OS_ANDROID)
    include(cmake/linux/default_libs.cmake)
elseif (OS_DARWIN)
    include(cmake/darwin/default_libs.cmake)
elseif (OS_FREEBSD)
    include(cmake/freebsd/default_libs.cmake)
endif ()

######################################
### Add targets below this comment ###
######################################

set (CMAKE_POSTFIX_VARIABLE "CMAKE_${CMAKE_BUILD_TYPE_UC}_POSTFIX")

if (MAKE_STATIC_LIBRARIES)
    set (CMAKE_POSITION_INDEPENDENT_CODE OFF)
    if (OS_LINUX AND NOT ARCH_ARM)
        # Slightly more efficient code can be generated
        # It's disabled for ARM because otherwise ClickHouse cannot run on Android.
        set (CMAKE_CXX_FLAGS_RELWITHDEBINFO "${CMAKE_CXX_FLAGS_RELWITHDEBINFO} -fno-pie")
        set (CMAKE_C_FLAGS_RELWITHDEBINFO "${CMAKE_C_FLAGS_RELWITHDEBINFO} -fno-pie")
        set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,-no-pie")
    endif ()
else ()
    set (CMAKE_POSITION_INDEPENDENT_CODE ON)
endif ()

# https://github.com/include-what-you-use/include-what-you-use
option (USE_INCLUDE_WHAT_YOU_USE "Automatically reduce unneeded includes in source code (external tool)" OFF)

if (USE_INCLUDE_WHAT_YOU_USE)
    find_program(IWYU_PATH NAMES include-what-you-use iwyu)
    if (NOT IWYU_PATH)
        message(FATAL_ERROR "Could not find the program include-what-you-use")
    endif()
    if (${CMAKE_VERSION} VERSION_LESS "3.3.0")
        message(FATAL_ERROR "include-what-you-use requires CMake version at least 3.3.")
    endif()
endif ()

if (ENABLE_TESTS)
    message (STATUS "Unit tests are enabled")
else()
    message(STATUS "Unit tests are disabled")
endif ()

enable_testing() # Enable for tests without binary

# when installing to /usr - place configs to /etc but for /usr/local place to /usr/local/etc
if (CMAKE_INSTALL_PREFIX STREQUAL "/usr")
    set (CLICKHOUSE_ETC_DIR "/etc")
else ()
    set (CLICKHOUSE_ETC_DIR "${CMAKE_INSTALL_PREFIX}/etc")
endif ()

message (STATUS
    "Building for: ${CMAKE_SYSTEM} ${CMAKE_SYSTEM_PROCESSOR} ${CMAKE_LIBRARY_ARCHITECTURE} ;
    USE_STATIC_LIBRARIES=${USE_STATIC_LIBRARIES}
    MAKE_STATIC_LIBRARIES=${MAKE_STATIC_LIBRARIES}
    SPLIT_SHARED=${SPLIT_SHARED_LIBRARIES}
    UNBUNDLED=${UNBUNDLED}
    CCACHE=${CCACHE_FOUND} ${CCACHE_VERSION}")

include (GNUInstallDirs)
include (cmake/contrib_finder.cmake)

find_contrib_lib(double-conversion) # Must be before parquet
include (cmake/find/ssl.cmake)
include (cmake/find/ldap.cmake) # after ssl
include (cmake/find/icu.cmake)
include (cmake/find/xz.cmake)
include (cmake/find/zlib.cmake)
include (cmake/find/zstd.cmake)
include (cmake/find/ltdl.cmake) # for odbc
# openssl, zlib before poco
include (cmake/find/sparsehash.cmake)
include (cmake/find/re2.cmake)
include (cmake/find/krb5.cmake)
include (cmake/find/libgsasl.cmake)
include (cmake/find/cyrus-sasl.cmake)
include (cmake/find/rdkafka.cmake)
include (cmake/find/libuv.cmake) # for amqpcpp and cassandra
include (cmake/find/amqpcpp.cmake)
include (cmake/find/capnp.cmake)
include (cmake/find/llvm.cmake)
include (cmake/find/h3.cmake)
include (cmake/find/libxml2.cmake)
include (cmake/find/brotli.cmake)
include (cmake/find/protobuf.cmake)
include (cmake/find/grpc.cmake)
include (cmake/find/pdqsort.cmake)
include (cmake/find/miniselect.cmake)
include (cmake/find/hdfs3.cmake) # uses protobuf
include (cmake/find/poco.cmake)
include (cmake/find/curl.cmake)
include (cmake/find/s3.cmake)
include (cmake/find/base64.cmake)
include (cmake/find/parquet.cmake)
include (cmake/find/simdjson.cmake)
include (cmake/find/fast_float.cmake)
include (cmake/find/rapidjson.cmake)
include (cmake/find/fastops.cmake)
include (cmake/find/odbc.cmake)
include (cmake/find/nanodbc.cmake)
include (cmake/find/sqlite.cmake)
include (cmake/find/rocksdb.cmake)
include (cmake/find/libpqxx.cmake)
include (cmake/find/nuraft.cmake)
include (cmake/find/yaml-cpp.cmake)
include (cmake/find/s2geometry.cmake)
include (cmake/find/nlp.cmake)
include (cmake/find/bzip2.cmake)

if(NOT USE_INTERNAL_PARQUET_LIBRARY)
    set (ENABLE_ORC OFF CACHE INTERNAL "")
endif()
include (cmake/find/orc.cmake)

include (cmake/find/avro.cmake)
include (cmake/find/msgpack.cmake)
include (cmake/find/cassandra.cmake)
include (cmake/find/sentry.cmake)
include (cmake/find/stats.cmake)
include (cmake/find/datasketches.cmake)

set (USE_INTERNAL_CITYHASH_LIBRARY ON CACHE INTERNAL "")
find_contrib_lib(cityhash)

find_contrib_lib(farmhash)

if (ENABLE_TESTS)
    include (cmake/find/gtest.cmake)
endif ()

# Need to process before "contrib" dir:
include (cmake/find/mysqlclient.cmake)

# When testing for memory leaks with Valgrind, don't link tcmalloc or jemalloc.

include (cmake/print_flags.cmake)

if (TARGET global-group)
    install (EXPORT global DESTINATION cmake)
endif ()

add_subdirectory (contrib EXCLUDE_FROM_ALL)

if (NOT ENABLE_JEMALLOC)
    message (WARNING "Non default allocator is disabled. This is not recommended for production builds.")
endif ()

macro (add_executable target)
    # invoke built-in add_executable
    # explicitly acquire and interpose malloc symbols by clickhouse_malloc
    # if GLIBC_COMPATIBILITY is ON and ENABLE_THINLTO is on than provide memcpy symbol explicitly to neutrialize thinlto's libcall generation.
    if (GLIBC_COMPATIBILITY AND ENABLE_THINLTO)
        _add_executable (${ARGV} $<TARGET_OBJECTS:clickhouse_malloc> $<TARGET_OBJECTS:memcpy>)
    else ()
        _add_executable (${ARGV} $<TARGET_OBJECTS:clickhouse_malloc>)
    endif ()

    get_target_property (type ${target} TYPE)
    if (${type} STREQUAL EXECUTABLE)
        # disabled for TSAN and gcc since libtsan.a provides overrides too
        if (TARGET clickhouse_new_delete)
            # operator::new/delete for executables (MemoryTracker stuff)
            target_link_libraries (${target} PRIVATE clickhouse_new_delete)
        endif()

        # In case of static jemalloc, because zone_register() is located in zone.c and
        # is never used outside (it is declared as constructor) it is omitted
        # by the linker, and so jemalloc will not be registered as system
        # allocator under osx [1], and clickhouse will SIGSEGV.
        #
        #   [1]: https://github.com/jemalloc/jemalloc/issues/708
        #
        # About symbol name:
        # - _zone_register not zone_register due to Mach-O binary format,
        # - _je_zone_register due to JEMALLOC_PRIVATE_NAMESPACE=je_ under OS X.
        # - but jemalloc-cmake does not run private_namespace.sh
        #   so symbol name should be _zone_register
        if (ENABLE_JEMALLOC AND MAKE_STATIC_LIBRARIES AND OS_DARWIN)
            set_property(TARGET ${target} APPEND PROPERTY LINK_OPTIONS -u_zone_register)
        endif()
    endif()
endmacro()

set(ConfigIncludePath ${CMAKE_CURRENT_BINARY_DIR}/includes/configs CACHE INTERNAL "Path to generated configuration files.")
include_directories(${ConfigIncludePath})

# Add as many warnings as possible for our own code.
include (cmake/warnings.cmake)

# Check if needed compiler flags are supported
include (cmake/check_flags.cmake)

add_subdirectory (base)
add_subdirectory (src)
add_subdirectory (programs)
add_subdirectory (tests)
add_subdirectory (utils)

include (cmake/print_include_directories.cmake)

include (cmake/sanitize_target_link_libraries.cmake)
