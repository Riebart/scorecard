var myApp = angular.module('submissionApp', ['ngResource']);

myApp.controller('submissionController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        $scope.submission_status = null;
        $scope.flagText = "";
        $scope.teamText = "";
        $scope.submitting = false;
        $scope.FlagResource = $resource(API_ENDPOINT + "/flag");
    };

    $scope.inputKeyPressed = function (keyEvent) {
        $scope.submission_status = null;
    };

    $scope.submitFlag = function () {
        if (($scope.teamText == null) || ($scope.teamText == "")) {
            $scope.submission_status = 'failure';
            return false;
        }
        if (($scope.flagText == null) || ($scope.flagText == "")) {
            $scope.submission_status = 'failure';
            return false;
        }
        if (isNaN(parseInt($scope.teamText))) {
            $scope.submission_status = 'failure_parse';
            return false;
        }

        $scope.submitting = true;
        $scope.FlagResource.save({
            team: $scope.teamText,
            flag: $scope.flagText
        }, function (response) {
            if ('valid_flag' in response) {
                if (response.valid_flag) {
                    $scope.submission_status = 'success';
                }
                else {
                    $scope.submission_status = 'invalid';
                }
            }
            $scope.submitting = false;
        });
    };

    $scope.$on('async_init', function () {
        $scope.init();
    });

    $scope.$emit('async_init');
}]);
