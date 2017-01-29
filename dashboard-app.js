var myApp = angular.module('dashboardApp', ['ngResource']);

myApp.controller('scoreboardController', ['$scope', '$rootScope', '$resource', '$timeout', function ($scope, $rootScope, $resource, $timeout) {

    $scope.init = function () {
        // The scores, on initialization, are an empty list.
        $scope.scores = {};
        $scope.ScoresResource = $resource(API_ENDPOINT + "/score/:team");
    };

    $scope.PopulateScores = function () {
        for (i in TEAMS) {
            t = TEAMS[i];
            // For each team, retrieve the score for that team.
            $scope.ScoresResource.get({
                team: t.toString()
            }, function(score) {
                $scope.scores[score.Team] = score.Score;
            });
        }
        return true;
    }

    $scope.ScoresRefresh = function () {
        $scope.PopulateScores();
        var poll = function () {
            $timeout(function () {
                if ($scope.PopulateScores()) {
                    poll();
                }
            }, 10000);
        };
        poll();
    };

    $scope.$on('async_init', function () {
        $scope.init();
        $scope.ScoresRefresh();
    });

    $scope.$emit('async_init');
}]);
